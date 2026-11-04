"""Isolated application regressions; never touches the user's history."""
import asyncio
import io
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_data = tempfile.TemporaryDirectory(prefix="sharp-tests-")
os.environ["SHARP_DATA_DIR"] = _data.name

from PIL import Image, ImageOps
from fastapi import HTTPException, UploadFile
from app import main, db, image_io
from app.models import Generation


def picture(mode="RGB", orientation=None, fmt="PNG"):
    image = Image.new(mode, (12, 8))
    if mode == "RGB":
        for y in range(8):
            for x in range(12):
                image.putpixel((x, y), (x * 20, y * 30, (x + y) * 10))
    exif = Image.Exif()
    if orientation:
        exif[274] = orientation
    exif[41989] = 50
    out = io.BytesIO()
    image.save(out, format=fmt, exif=exif)
    return out.getvalue()


class Regressions(unittest.TestCase):
    def setUp(self):
        if db._engine is not None:
            db._engine.dispose()
        db.init_db()
        self.ready = patch.object(main.sharp_runner, "is_ready", return_value=True)
        self.ready.start()

    def tearDown(self):
        self.ready.stop()
        db._engine.dispose()

    def test_decode_modes_orientation_and_focal(self):
        for mode in ("RGB", "P", "L", "RGBA"):
            for orientation in range(1, 9):
                data = picture(mode, orientation)
                im, focal = image_io.decode_image(io.BytesIO(data))
                self.assertEqual(im.mode, "RGB")
                self.assertEqual(im.size, (8, 12) if orientation >= 5 else (12, 8))
                self.assertEqual(focal, 50)
                with Image.open(io.BytesIO(data)) as original:
                    expected = ImageOps.exif_transpose(original).convert("RGB")
                    self.assertEqual(im.tobytes(), expected.tobytes())

    def test_heic(self):
        import pillow_heif
        out = io.BytesIO()
        pillow_heif.from_pillow(Image.new("RGB", (12, 8))).save(out)
        im, _ = image_io.decode_image(io.BytesIO(out.getvalue()))
        self.assertEqual(im.size, (12, 8))

    def upload(self, data):
        return main.generate(UploadFile(filename="test.png", file=io.BytesIO(data)), "{}")

    def test_invalid_upload_leaves_no_files(self):
        before = set(Path(_data.name).rglob("*"))
        for data in (b"", b"broken", b"x" * (main.MAX_BYTES + 1)):
            with self.assertRaises(HTTPException):
                asyncio.run(self.upload(data))
        self.assertEqual(before, set(Path(_data.name).rglob("*")))

    def test_predict_and_database_failure_cleanup(self):
        before = set(Path(_data.name).rglob("*"))
        def fail(image, ply, **kw):
            ply.write_bytes(b"partial")
            kw["web_output_path"].write_bytes(b"partial")
            raise RuntimeError("export failed")
        with patch.object(main.sharp_runner, "predict", side_effect=fail):
            with self.assertRaises(HTTPException):
                asyncio.run(self.upload(picture()))
        self.assertEqual(before, set(Path(_data.name).rglob("*")))
        with patch.object(main.sharp_runner, "predict", side_effect=self.fake_predict), patch.object(db, "get_session", side_effect=RuntimeError("db failed")):
            with self.assertRaises(Exception):
                asyncio.run(self.upload(picture()))
        self.assertEqual(before, set(Path(_data.name).rglob("*")))

    @staticmethod
    def fake_predict(image, ply, **kw):
        ply.write_bytes(b"ply")
        kw["web_output_path"].write_bytes(b"splat")
        return SimpleNamespace(num_points=4, web_points=1, detected_focal35=50)

    def test_shared_source_and_utc(self):
        with patch.object(main.sharp_runner, "predict", side_effect=self.fake_predict):
            first = asyncio.run(self.upload(picture()))
            second = main.regenerate(first["id"], "{}")
        self.assertTrue(first["createdAt"].endswith("+00:00"))
        with db.get_session() as session:
            row = session.get(Generation, second["id"])
            source, thumb = row.image_path, row.thumb_path
        main.delete_generation(first["id"])
        self.assertTrue((main.UPLOAD_DIR / source).exists())
        self.assertTrue((main.THUMB_DIR / thumb).exists())
        main.delete_generation(second["id"])
        self.assertFalse((main.UPLOAD_DIR / source).exists())
        self.assertFalse((main.THUMB_DIR / thumb).exists())

    def test_failed_regeneration_and_commit_preserve_source(self):
        from sqlmodel import Session
        with patch.object(main.sharp_runner, "predict", side_effect=self.fake_predict):
            first = asyncio.run(self.upload(picture()))
        before = set(Path(_data.name).rglob("*"))
        with patch.object(main.sharp_runner, "predict", side_effect=self.fake_predict), patch.object(Session, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaises(RuntimeError):
                main.regenerate(first["id"], "{}")
        self.assertEqual(before, set(Path(_data.name).rglob("*")))
        self.assertEqual([g["id"] for g in main.history()], [first["id"]])
        main.delete_generation(first["id"])

    def test_delete_waits_for_regeneration(self):
        started, finish = threading.Event(), threading.Event()
        with patch.object(main.sharp_runner, "predict", side_effect=self.fake_predict):
            first = asyncio.run(self.upload(picture()))
        def slow(*a, **kw):
            started.set()
            self.assertTrue(finish.wait(5))
            return self.fake_predict(*a, **kw)
        with patch.object(main.sharp_runner, "predict", side_effect=slow), ThreadPoolExecutor(2) as pool:
            rerun = pool.submit(main.regenerate, first["id"], "{}")
            self.assertTrue(started.wait(5))
            deletion = pool.submit(main.delete_generation, first["id"])
            time.sleep(.05)
            self.assertFalse(deletion.done())
            finish.set()
            second = rerun.result(5)
            deletion.result(5)
        with db.get_session() as session:
            source = session.get(Generation, second["id"]).image_path
        self.assertTrue((main.UPLOAD_DIR / source).exists())
        main.delete_generation(second["id"])

    def test_event_loop_responsive_and_serial(self):
        active = 0
        peak = 0
        def slow(*a, **kw):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(.3)
            result = self.fake_predict(*a, **kw)
            active -= 1
            return result
        async def scenario():
            tasks = [asyncio.create_task(self.upload(picture())) for _ in range(2)]
            await asyncio.sleep(.05)
            self.assertFalse(any(t.done() for t in tasks), "inference blocked the event loop")
            await asyncio.to_thread(main.history)
            self.assertFalse(all(t.done() for t in tasks))
            return await asyncio.gather(*tasks)
        with patch.object(main.sharp_runner, "predict", side_effect=slow):
            records = asyncio.run(scenario())
        self.assertEqual(peak, 1)
        for record in records:
            main.delete_generation(record["id"])


if __name__ == "__main__":
    unittest.main()

async (page) => {
  const base = 'http://127.0.0.1:8765';
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  const onError = e => errors.push(e.message);
  page.on('pageerror', onError);
  try {
    await page.unrouteAll();
    const response = await page.request.get(`${base}/api/history`);
    const records = await response.json();
    check(records.length > 0, 'Generate a record in the isolated validation server first');
    const old = records.map((g, i) => ({...g, params:i ? null : {density:.5,scale:1.1}, createdAt:'2026-10-27T12:00:00'}));
    let health = false;
    let historyFail = true;
    await page.route('**/api/health', r => health ? r.fulfill({json:{ready:true,error:null,cudaAvailable:true,device:'cuda'}}) : r.abort());
    await page.route('**/api/history', r => historyFail ? r.fulfill({status:503,json:{detail:'history failure'}}) : r.fulfill({json:old}));
    await page.goto(base);
    await page.getByText('连接失败', {exact:true}).waitFor();
    check(await page.getByRole('button',{name:'上传并生成',exact:true}).isDisabled(), 'Offline upload must be disabled');
    historyFail = false;
    await page.getByRole('button',{name:'重试',exact:true}).click();
    await page.locator('.viewer-hint').waitFor({timeout:60000});
    await page.locator('.param-summary summary').click();
    await page.getByText('旧版 0.50', {exact:true}).waitFor();
    health = true;
    await page.getByText('就绪', {exact:true}).waitFor({timeout:8000});
    let release;
    let calls = 0;
    const gate = new Promise(resolve => release = resolve);
    await page.route('**/api/regenerate/*', async r => { calls++; await gate; await r.fulfill({status:500,json:{detail:'controlled failure'}}); });
    const canvas = await page.locator('canvas').elementHandle();
    await page.evaluate(() => { const b = document.querySelector('.rerun'); b.click(); b.click(); });
    await page.locator('.task-overlay').waitFor();
    check(await page.locator('.thumb').first().isDisabled(), 'History must be locked');
    check(await canvas.evaluate(c => c.isConnected), 'Preview must remain during inference');
    release();
    await page.getByRole('alert').filter({hasText:'controlled failure'}).waitFor();
    check(calls === 1, 'Duplicate submission');
    check(await canvas.evaluate(c => c.isConnected), 'Preview lost after inference failure');
    check(await page.getByRole('link',{name:'下载 PLY'}).isVisible(), 'Download lost after failure');
    await page.unrouteAll();
    await page.route('**/files/gaussians/*.splat', r => r.fulfill({status:500,body:'load failure'}));
    await page.reload();
    await page.locator('.viewer-error').waitFor();
    await page.waitForFunction(() => document.querySelectorAll('canvas').length === 0);
    check(errors.length === 0, errors.join('\n'));
    return {passed:true, checks:['offline recovery','history retry','legacy parameters','duplicate submission','history lock','preview preservation','download preservation','failed viewer disposal'], unhandledErrors:errors};
  } finally {
    page.off('pageerror', onError);
    await page.unrouteAll();
    await page.reload();
  }
}

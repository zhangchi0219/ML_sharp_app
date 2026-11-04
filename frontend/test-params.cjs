const {test} = require('node:test');
const assert = require('node:assert/strict');
const ts = require('typescript');
const fs = require('node:fs');
const vm = require('node:vm');
function load(name) {
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(`${__dirname}/src/lib/${name}.ts`, 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
  vm.runInNewContext(code, {exports, require:(p)=>load(p.replace('./',''))});
  return exports;
}
const types = load('types');
const meta = load('paramMeta');
test('old partial parameters do not crash either summary',()=> {
  const rows = meta.paramRows({scale:1.1,density:.5},null);
  assert.match(rows[0].value,/旧版.*0.50/);
  assert.ok(meta.summaryLine({originalFilename:'old',params:{density:.5}}));
});
test('normalization filters legacy keys and invalid values',()=> {
  const p=types.normalizeParams({density:.5,scale:null,detail:0,colorGain:NaN,maxScale:100});
  assert.equal(p.scale,1);
  assert.equal(p.detail,1);
  assert.equal(p.colorGain,1);
  assert.equal(p.maxScale,10);
  assert.equal(p.density,undefined);
});
test('missing parameters produce independent defaults',()=> {
  const p=types.normalizeParams(null);
  p.scale=2;
  assert.equal(types.DEFAULT_PARAMS.scale,1);
});

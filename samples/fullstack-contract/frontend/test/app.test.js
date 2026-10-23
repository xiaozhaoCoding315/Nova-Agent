const test = require('node:test');
const assert = require('node:assert');
const { add } = require('../src/app.js');

test('frontend add', () => {
  assert.strictEqual(add(4, 5), 9);
});

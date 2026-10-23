const test = require('node:test');
const assert = require('node:assert');
const { add } = require('../src/math.js');

test('add returns the sum', () => {
  assert.strictEqual(add(1, 2), 3);
});

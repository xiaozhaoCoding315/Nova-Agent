const fs = require('node:fs');

const files = ['src/math.js', 'test/math.test.js', 'scripts/lint.js', 'scripts/build.js'];
for (const file of files) {
  if (!fs.readFileSync(file, 'utf8').trim()) {
    console.error(`empty file: ${file}`);
    process.exit(1);
  }
}
console.log('lint ok');

const fs = require('node:fs');

const files = ['frontend/src/app.js', 'frontend/test/app.test.js'];
for (const file of files) {
  if (!fs.readFileSync(file, 'utf8').trim()) {
    console.error(`empty file: ${file}`);
    process.exit(1);
  }
}
console.log('lint ok');

const fs = require('node:fs');
const path = require('node:path');

fs.mkdirSync('dist', { recursive: true });
fs.copyFileSync(path.join('src', 'math.js'), path.join('dist', 'math.js'));
console.log('build ok');

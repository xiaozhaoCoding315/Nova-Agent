const fs = require('node:fs');
const path = require('node:path');

fs.mkdirSync('frontend/dist', { recursive: true });
fs.copyFileSync(path.join('frontend', 'src', 'app.js'), path.join('frontend', 'dist', 'app.js'));
console.log('build ok');

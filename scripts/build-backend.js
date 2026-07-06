const { execSync } = require('child_process');
const path = require('path');

const isWin = process.platform === 'win32';
const backendDir = path.resolve(__dirname, '../packages/backend');
const pyinstallerPath = isWin
  ? path.join(backendDir, '.buildenv', 'Scripts', 'pyinstaller.exe')
  : path.join(backendDir, '.buildenv', 'bin', 'pyinstaller');

console.log(`Building backend using PyInstaller: ${pyinstallerPath}`);

try {
  execSync(`"${pyinstallerPath}" backend.spec --noconfirm`, {
    cwd: backendDir,
    stdio: 'inherit'
  });
  console.log('Backend built successfully.');
} catch (e) {
  console.error('Backend build failed:', e.message);
  process.exit(1);
}

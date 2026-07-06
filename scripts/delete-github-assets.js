const https = require('https');
const fs = require('fs');
const path = require('path');

// Read version from package.json
const pkgPath = path.resolve(__dirname, '../apps/desktop/package.json');
if (!fs.existsSync(pkgPath)) {
  console.error('Could not find apps/desktop/package.json');
  process.exit(1);
}
const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
const version = pkg.version;
if (!version) {
  console.error('No version found in package.json');
  process.exit(1);
}

const token = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
if (!token) {
  console.log('No GH_TOKEN or GITHUB_TOKEN environment variable found. Skipping release cleanup.');
  process.exit(0);
}

const owner = 'Smriti-kinra';
const repo = 'Cursor-for-Urban-Planners';

const headers = {
  'User-Agent': 'Electron-Builder-Cleanup-Script',
  'Authorization': `token ${token}`,
  'Accept': 'application/vnd.github.v3+json'
};

function makeRequest(options, postData = null) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        resolve({ statusCode: res.statusCode, body: data, headers: res.headers });
      });
    });
    req.on('error', (e) => reject(e));
    if (postData) req.write(postData);
    req.end();
  });
}

async function run() {
  console.log('Fetching all releases in the repository...');
  let releases = [];
  try {
    const res = await makeRequest({
      hostname: 'api.github.com',
      path: `/repos/${owner}/${repo}/releases?per_page=100`,
      method: 'GET',
      headers
    });
    if (res.statusCode === 200) {
      releases = JSON.parse(res.body);
    } else {
      console.error(`Failed to list releases: Status ${res.statusCode}`, res.body);
      process.exit(1);
    }
  } catch (e) {
    console.error('Error listing releases:', e.message);
    process.exit(1);
  }

  if (releases.length === 0) {
    console.log('No releases found in the repository.');
    return;
  }

  console.log(`Found ${releases.length} releases. Deleting all of them to clean the repository...`);
  for (const release of releases) {
    const tag = release.tag_name;
    console.log(`Deleting release "${release.name || tag}" (ID: ${release.id}, Tag: ${tag})...`);
    
    // 1. Delete release
    try {
      const deleteReleaseRes = await makeRequest({
        hostname: 'api.github.com',
        path: `/repos/${owner}/${repo}/releases/${release.id}`,
        method: 'DELETE',
        headers
      });
      if (deleteReleaseRes.statusCode === 204) {
        console.log(`Successfully deleted release ID ${release.id}`);
      } else {
        console.error(`Failed to delete release ID ${release.id}: Status ${deleteReleaseRes.statusCode}`);
      }
    } catch (e) {
      console.error(`Error deleting release ID ${release.id}:`, e.message);
    }

    // 2. Delete git tag ref
    console.log(`Deleting git tag ref: ${tag}...`);
    try {
      const deleteTagRes = await makeRequest({
        hostname: 'api.github.com',
        path: `/repos/${owner}/${repo}/git/refs/tags/${tag}`,
        method: 'DELETE',
        headers
      });
      if (deleteTagRes.statusCode === 204) {
        console.log(`Successfully deleted git tag ref ${tag}`);
      } else {
        console.log(`Tag ref deletion status for ${tag}: ${deleteTagRes.statusCode}`);
      }
    } catch (e) {
      console.error(`Error deleting tag ref ${tag}:`, e.message);
    }
  }
  console.log('Cleanup completed successfully.');
}

run().catch((e) => {
  console.error('Cleanup script crashed:', e);
  process.exit(1);
});

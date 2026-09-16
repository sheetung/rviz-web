import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const args = process.argv.slice(2)
const checkOnly = args.includes('--check')
const positional = args.filter(arg => arg !== '--check')
const [component, requestedVersion] = positional
const versionPattern = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/

if (!['frontend', 'backend', 'management'].includes(component) || positional.length > 2) {
  throw new Error('Usage: node scripts/sync-version.mjs <frontend|backend|management> [version] [--check]')
}
if (requestedVersion && !versionPattern.test(requestedVersion)) {
  throw new Error(`Invalid semantic version: ${requestedVersion}`)
}

const mismatches = []
let version

if (component === 'frontend') {
  const packagePath = resolve(root, 'frontend/package.json')
  const lockPath = resolve(root, 'frontend/package-lock.json')
  const packageDocument = JSON.parse(readFileSync(packagePath, 'utf8'))
  const lockDocument = JSON.parse(readFileSync(lockPath, 'utf8'))
  version = requestedVersion || packageDocument.version

  if (!versionPattern.test(version)) throw new Error(`Invalid frontend version: ${version}`)
  if (packageDocument.version !== version) mismatches.push(packagePath)
  if (lockDocument.version !== version) mismatches.push(lockPath)
  if (lockDocument.packages?.['']?.version !== version) {
    mismatches.push(`${lockPath} packages[""]`)
  }

  if (!checkOnly) {
    packageDocument.version = version
    lockDocument.version = version
    if (lockDocument.packages?.['']) lockDocument.packages[''].version = version
    writeFileSync(packagePath, `${JSON.stringify(packageDocument, null, 2)}\n`)
    writeFileSync(lockPath, `${JSON.stringify(lockDocument, null, 2)}\n`)
  }
} else if (component === 'backend') {
  const versionPath = resolve(root, 'backend/VERSION')
  const current = readFileSync(versionPath, 'utf8').trim()
  version = requestedVersion || current
  if (!versionPattern.test(version)) throw new Error(`Invalid native version: ${version}`)
  if (current !== version) mismatches.push(versionPath)
  if (!checkOnly) writeFileSync(versionPath, `${version}\n`)
} else {
  const pyprojectPath = resolve(root, 'backend/management/pyproject.toml')
  const lockPath = resolve(root, 'backend/management/uv.lock')
  const pyproject = readFileSync(pyprojectPath, 'utf8')
  const lock = readFileSync(lockPath, 'utf8')
  const pyprojectPattern = /^version = "([^"]+)"/m
  const lockPattern = /(name = "rviz-web-management"\r?\nversion = ")[^"]+("\r?\n)/
  const currentVersion = pyproject.match(pyprojectPattern)?.[1]
  const lockedVersion = lock.match(lockPattern)?.[0].match(/version = "([^"]+)"/)?.[1]
  version = requestedVersion || currentVersion

  if (!versionPattern.test(version || '')) throw new Error(`Invalid backend version: ${version}`)
  if (currentVersion !== version) mismatches.push(pyprojectPath)
  if (lockedVersion !== version) mismatches.push(lockPath)

  if (!checkOnly) {
    writeFileSync(
      pyprojectPath,
      pyproject.replace(pyprojectPattern, `version = "${version}"`)
    )
    writeFileSync(
      lockPath,
      lock.replace(lockPattern, (_match, prefix, suffix) => `${prefix}${version}${suffix}`)
    )
  }
}

if (checkOnly && mismatches.length > 0) {
  throw new Error(`${component} version ${version} is not synchronized:\n${mismatches.join('\n')}`)
}

console.log(`${checkOnly ? 'Verified' : 'Synchronized'} ${component} ${version}`)

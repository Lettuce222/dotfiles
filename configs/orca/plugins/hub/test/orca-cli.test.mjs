import assert from 'node:assert/strict'
import { test } from 'node:test'
import { resolveOrcaCli } from '../src/orca-cli.mjs'

const CLI = '/Applications/Orca.app/Contents/Resources/bin/orca'
const only = (path) => (candidate) => candidate === path

test('resolveOrcaCli finds the CLI of the app from its main binary and from its helper', () => {
  assert.equal(resolveOrcaCli('/Applications/Orca.app/Contents/MacOS/Orca', only(CLI)), CLI)
  assert.equal(resolveOrcaCli('/Applications/Orca.app/Contents/Frameworks/Orca Helper.app/Contents/MacOS/Orca Helper', only(CLI)), CLI)
})

test('resolveOrcaCli prefers a CLI in the innermost bundle, and falls back to orca on PATH', () => {
  const inner = '/A.app/Contents/Frameworks/B.app/Contents/Resources/bin/orca'
  assert.equal(resolveOrcaCli('/A.app/Contents/Frameworks/B.app/Contents/MacOS/B', () => true), inner)
  assert.equal(resolveOrcaCli('/usr/local/bin/node', () => false), 'orca')
})

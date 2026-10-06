import { Ajv } from 'ajv'
import { readdirSync, readFileSync } from 'node:fs'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Contract tests: the shared fixtures in schema/fixtures must be accepted
// (valid) or rejected (invalid) by the JSON Schemas the TS types come from.

const schemaRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../schema')
const jsonschemaDir = join(schemaRoot, 'jsonschema')
const fixturesDir = join(schemaRoot, 'fixtures')

const readJson = (path: string): unknown => JSON.parse(readFileSync(path, 'utf8'))

const ajv = new Ajv({ allErrors: true })
const schemaFiles = readdirSync(jsonschemaDir).filter((f) => f.endsWith('.schema.json'))
for (const file of schemaFiles) {
  ajv.addSchema(readJson(join(jsonschemaDir, file)) as object, file)
}

function cases(set: 'valid' | 'invalid'): [string, string][] {
  const setDir = join(fixturesDir, set)
  return readdirSync(setDir).flatMap((kind) =>
    readdirSync(join(setDir, kind))
      .filter((f) => f.endsWith('.json'))
      .map((f): [string, string] => [`${kind}/${basename(f, '.json')}`, join(setDir, kind, f)]),
  )
}

function validate(id: string, path: string): boolean {
  const kind = id.split('/')[0]
  const check = ajv.getSchema(`${kind}.schema.json`)
  if (!check) throw new Error(`no schema for fixture kind ${kind}`)
  return check(readJson(path)) === true
}

describe('schema fixtures', () => {
  it.each(cases('valid'))('accepts %s', (id, path) => {
    expect(validate(id, path)).toBe(true)
  })

  it.each(cases('invalid'))('rejects %s', (id, path) => {
    expect(validate(id, path)).toBe(false)
  })
})

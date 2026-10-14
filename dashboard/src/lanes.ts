/** How many rows of markers the match timeline stacks. */
export const LANES = 3

/**
 * A lane for each marker (by its position along the strip), so markers
 * close together stack instead of hiding each other. Past the last lane, they overlap.
 */
export function lanes(positions: number[], gap: number): number[] {
  const order = positions.map((x, i) => [x, i] as const).sort((a, b) => a[0] - b[0])
  const ends: number[] = []
  const result = new Array<number>(positions.length)
  for (const [x, i] of order) {
    let lane = ends.findIndex((end) => x - end >= gap)
    if (lane === -1) lane = ends.length < LANES ? ends.length : LANES - 1
    ends[lane] = x
    result[i] = lane
  }
  return result
}

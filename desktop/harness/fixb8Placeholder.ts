/**
 * FIX-B8 D: the Games search box's new placeholder ("Opponent, opening, game id or link"; the first draft, "Opponent, opening, ECO, game id or link", was 15 px too wide) fits its box at
 * 1440 x 940 and 1280 x 720: the placeholder's text width (canvas measureText with the input's computed font)
 * against the input's content width. Run from desktop/: node harness/fixb8Placeholder.ts (figures in review/scratch/fixb8/placeholder_check.out)
 */
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { harnessBrowser } from './browser.ts'

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const server = await createServer({ configFile: resolve(desktop, 'vite.harness.config.ts'), server: { port: 0, host: '127.0.0.1' }, logLevel: 'silent' })
await server.listen()
const base = server.resolvedUrls!.local[0].replace(/\/$/, '')
const browser = await harnessBrowser.launch({ headless: true })
for (const [w, h] of [[1440, 940], [1280, 720]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } })
  await page.goto(base + '/?screen=games&state=games-kinds')
  const input = page.locator('.search input')
  await input.waitFor()
  const m = await input.evaluate((el: HTMLInputElement) => {
    const cs = getComputedStyle(el)
    const ctx = document.createElement('canvas').getContext('2d')!
    ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`
    const content = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
    const r = el.getBoundingClientRect()
    return { placeholder: el.placeholder, text: Math.ceil(ctx.measureText(el.placeholder).width), content, box: [r.x, r.y, r.width, r.height], vw: innerWidth }
  })
  console.log(`${w}x${h}: "${m.placeholder}" text ${m.text} px in a ${m.content} px content box (${m.text <= m.content ? 'fits' : 'CLIPPED by ' + (m.text - m.content) + ' px'}); input box ${m.box.map((x: number) => Math.round(x)).join(',')}, inside the viewport: ${m.box[0] >= 0 && m.box[0] + m.box[2] <= m.vw}`)
  await page.close()
}
await browser.close()
await server.close()

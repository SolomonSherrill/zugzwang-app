/** FRIENDS-2 D: the friends list's columns, header against rows, as pixel offsets (the row is now the link's
 *  four columns beside the Challenge cell). Prints one line per column: header left, row left, difference.
 *   cd desktop && [ZUGZWANG_HARNESS_BROWSER=webkit] node harness/friends2Align.ts */
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { harnessBrowser, harnessBrowserName } from './browser.ts'

const here = dirname(fileURLToPath(import.meta.url))
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5231)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port }, logLevel: 'silent' })
await server.listen()
const browser = await harnessBrowser.launch({ headless: true })
const out: string[] = [`# The friends list's columns, header vs rows (harness/friends2Align.ts), ${harnessBrowserName}`]
try {
  for (const size of [{ width: 1440, height: 940 }, { width: 1280, height: 720 }]) {
    const ctx = await browser.newContext({ viewport: size })
    await ctx.addInitScript(() => localStorage.setItem('zugzwang-accounts', JSON.stringify({ chesscom: 'you_demo', lichess: '' })))
    const page = await ctx.newPage()
    await page.goto(`http://localhost:${port}/?screen=friends`)
    await page.locator('li.fli').first().waitFor()
    const m = await page.evaluate(() => {
      const head = [...document.querySelectorAll('.colhead > span')].map((e) => e.getBoundingClientRect())
      return [...document.querySelectorAll('li.fli')].map((li) => {
        // the Challenge cell by its content box (its 16 px right padding is the row's own, as the header's)
        const box = (e: Element) => {
          const r = e.getBoundingClientRect()
          const cs = getComputedStyle(e)
          return { left: r.left + parseFloat(cs.paddingLeft) * (e.classList.contains('end') ? 1 : 0), right: r.right - (e.classList.contains('end') ? parseFloat(cs.paddingRight) : 0) }
        }
        const cells = [...li.querySelectorAll(':scope > .row > *'), li.querySelector(':scope > .end')!].map(box)
        return { handle: li.textContent!.trim().split(/\s/)[0], d: cells.map((c, i) => [Math.round(head[i].left), Math.round(c.left), Math.round(c.left - head[i].left), Math.round(head[i].right - c.right)]) }
      })
    })
    out.push(`== ${size.width}x${size.height}`)
    for (const r of m) out.push(`  ${r.handle.padEnd(10)} ` + r.d.map(([h, c, dl, dr], i) => `col${i + 1} header ${h} row ${c} left ${dl >= 0 ? '+' : ''}${dl}px right ${dr >= 0 ? '+' : ''}${dr}px`).join(' | '))
    await ctx.close()
  }
} finally {
  await browser.close()
  await server.close()
}
console.log(out.join('\n'))

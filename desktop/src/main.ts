import { mount } from 'svelte'
import 'chessground/assets/chessground.base.css'
import 'chessground/assets/chessground.cburnett.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import './app.css'
import App from './App.svelte'

const app = mount(App, {
  target: document.getElementById('app')!,
})

export default app

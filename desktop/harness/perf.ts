import { mount } from 'svelte'
import 'chessground/assets/chessground.base.css'
import 'chessground/assets/chessground.cburnett.css'
import '../src/lib/styles/fonts.css'
import '../src/lib/styles/tokens.css'
import '../src/app.css'
import Perf from './Perf.svelte'

mount(Perf, { target: document.getElementById('app')! })

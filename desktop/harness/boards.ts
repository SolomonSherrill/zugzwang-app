import { mount } from 'svelte'
import 'chessground/assets/chessground.base.css'
import 'chessground/assets/chessground.cburnett.css'
import '../src/lib/styles/fonts.css'
import '../src/lib/styles/tokens.css'
import '../src/app.css'
import Boards from './Boards.svelte'

mount(Boards, { target: document.getElementById('app')! })

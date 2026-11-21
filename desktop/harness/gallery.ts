import { mount } from 'svelte'
import '../src/lib/styles/fonts.css'
import '../src/lib/styles/tokens.css'
import '../src/app.css'
import Gallery from './Gallery.svelte'

mount(Gallery, { target: document.getElementById('app')! })

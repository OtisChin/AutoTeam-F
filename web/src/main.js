import { createApp } from 'vue'
import App from './App.vue'
import { createThemeController, THEME_CONTROLLER_KEY } from './themePreference.js'
import './style.css'

const themeController = createThemeController()
const app = createApp(App)
app.provide(THEME_CONTROLLER_KEY, themeController)
app.mount('#app')

if (import.meta.hot) {
  import.meta.hot.dispose(() => themeController.dispose())
}

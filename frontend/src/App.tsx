import { LegacyShell } from './LegacyShell'
import { AppShell } from './shell/AppShell'

export default function App() {
  const legacy = new URLSearchParams(window.location.search).get('shell') === 'legacy'
  return legacy ? <LegacyShell /> : <AppShell />
}

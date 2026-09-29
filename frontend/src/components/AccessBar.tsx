/**
 * Плашка гостевого режима стенда и окно входа. Гость видит обезличенный набор
 * и кнопку «Вход»: пара логин/пароль у команды одна, регистрации нет. После
 * входа плашки нет вовсе, «Выйти» — в меню «…». В разработке плашки тоже нет.
 */

import { useEffect, useState, type FormEvent } from 'react'
import { Button, TextInput, ThemeProvider } from '@gravity-ui/uikit'
import { useStore } from '../store'
import { IconClose } from '../lib/icons'
import { login, useAccessMode } from '../lib/access'

const SUPPORT = 'amik@amik.am'

function LoginDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || !name || !password) return
    setBusy(true)
    setError('')
    const failed = await login(name, password)
    if (failed) {
      setError(failed)
      setBusy(false)
    }
  }

  return (
    <div className="b-login">
      <div className="b-login-scrim" onClick={onClose} aria-hidden="true" />
      <form className="b-login-card" role="dialog" aria-modal="true" aria-labelledby="b-login-title" onSubmit={submit}>
        <div className="b-login-head">
          <h2 id="b-login-title">Вход</h2>
          <Button view="flat" size="m" onClick={onClose} title="Закрыть">
            <IconClose />
          </Button>
        </div>
        <label className="b-login-field">
          <span>Логин</span>
          <TextInput
            size="xl"
            value={name}
            onUpdate={setName}
            autoComplete="username"
            autoFocus
            name="username"
          />
        </label>
        <label className="b-login-field">
          <span>Пароль</span>
          <TextInput
            size="xl"
            type="password"
            value={password}
            onUpdate={(value) => {
              setPassword(value)
              setError('')
            }}
            autoComplete="current-password"
            name="password"
            validationState={error ? 'invalid' : undefined}
            errorMessage={error}
          />
        </label>
        <Button type="submit" view="action" size="xl" width="max" loading={busy} disabled={!name || !password}>
          Войти
        </Button>
        <p className="b-login-help">
          Остались вопросы — <a href={`mailto:${SUPPORT}`}>{SUPPORT}</a>
        </p>
      </form>
    </div>
  )
}

export default function AccessBar() {
  // Плашка стоит над приложением, вне его ThemeProvider: полям и кнопкам нужен свой.
  const theme = useStore((s) => s.theme)
  const mode = useAccessMode()
  const [open, setOpen] = useState(false)

  if (mode !== 'guest') return null

  return (
    <ThemeProvider theme={theme} scoped>
      <div className="b-access" role="status">
        <span className="b-access-text">
          Гостевой режим<span className="b-access-long">: данные обезличены</span>
        </span>
        <Button view="outlined" size="s" onClick={() => setOpen(true)}>
          Вход
        </Button>
      </div>
      {open ? <LoginDialog onClose={() => setOpen(false)} /> : null}
    </ThemeProvider>
  )
}

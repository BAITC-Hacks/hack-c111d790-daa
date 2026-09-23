import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';
import {
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  LoaderCircle,
  LogOut,
  Monitor,
  Moon,
  ShieldCheck,
  Sun,
  UserRound,
  X,
} from 'lucide-react';
import { api, ApiError } from './api';

type Theme = 'light' | 'dark' | 'system';
type User = { id: string; name: string; email: string; job_title: string; created_at: string };
type AccountContextValue = { user: User; openProfile: () => void; openSettings: () => void };
const AccountContext = createContext<AccountContextValue | null>(null);
const logo = new URL('./assets/waresync.png', import.meta.url).href;

export function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase();
}

export function useAccount() {
  const value = useContext(AccountContext);
  if (!value) throw new Error('Account provider is required');
  return value;
}

export function savedTheme(): Theme {
  try {
    const value = localStorage.getItem('waresync-theme');
    if (value === 'light' || value === 'dark' || value === 'system') return value;
  } catch {
    /* Browser storage can be unavailable. */
  }
  return 'system';
}

export function applyTheme(theme: Theme) {
  const dark =
    theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
}

function ThemePicker({ theme, setTheme }: { theme: Theme; setTheme: (theme: Theme) => void }) {
  return (
    <div className="theme-options" role="group" aria-label="Тема оформления">
      {(
        [
          { id: 'light', label: 'Светлая', Icon: Sun },
          { id: 'dark', label: 'Тёмная', Icon: Moon },
          { id: 'system', label: 'Системная', Icon: Monitor },
        ] as const
      ).map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          className={theme === id ? 'selected' : ''}
          aria-pressed={theme === id}
          onClick={() => setTheme(id)}
        >
          <Icon size={21} />
          {label}
          {theme === id && <Check size={14} className="theme-check" />}
        </button>
      ))}
    </div>
  );
}

export function AccountRoot({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [panel, setPanel] = useState<'profile' | 'settings' | null>(null);
  const [theme, setTheme] = useState<Theme>(savedTheme);
  useEffect(() => {
    const update = () => applyTheme(theme);
    update();
    try {
      localStorage.setItem('waresync-theme', theme);
    } catch {
      /* Keep the in-memory preference. */
    }
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [theme]);
  useEffect(() => {
    let active = true;
    api<User>('/auth/me')
      .then((value) => {
        if (active) setUser(value);
      })
      .catch((e) => {
        if (active && (!(e instanceof ApiError) || e.status !== 401))
          setError('Не удалось подключиться к серверу. Проверьте соединение и обновите страницу.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    const expired = () => {
      setUser(null);
      setPanel(null);
      setError('Сессия завершена. Войдите ещё раз.');
    };
    window.addEventListener('waresync:session-expired', expired);
    return () => {
      active = false;
      window.removeEventListener('waresync:session-expired', expired);
    };
  }, []);

  if (loading)
    return (
      <div className="account-loading" role="status">
        <LoaderCircle className="spin" />
        Открываем WareSync…
      </div>
    );
  if (!user)
    return (
      <AuthScreen
        error={error}
        clearError={() => setError('')}
        theme={theme}
        setTheme={setTheme}
        onLogin={(value) => {
          setError('');
          setUser(value);
        }}
      />
    );
  return (
    <AccountContext.Provider
      value={{ user, openProfile: () => setPanel('profile'), openSettings: () => setPanel('settings') }}
    >
      <div key={user.id}>{children}</div>
      {panel && (
        <AccountPanel
          user={user}
          panel={panel}
          setPanel={setPanel}
          close={() => setPanel(null)}
          theme={theme}
          setTheme={setTheme}
          saved={setUser}
          loggedOut={() => {
            setPanel(null);
            setUser(null);
          }}
        />
      )}
    </AccountContext.Provider>
  );
}

function AuthScreen({
  onLogin,
  error: initialError,
  clearError,
  theme,
  setTheme,
}: {
  onLogin: (user: User) => void;
  error: string;
  clearError: () => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
}) {
  const [register, setRegister] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const rules = [
    { text: 'Не менее 8 символов', valid: password.length >= 8 },
    { text: 'Есть буква и цифра', valid: /\p{L}/u.test(password) && /\p{N}/u.test(password) },
    { text: 'Пароли совпадают', valid: !!confirmation && password === confirmation },
  ];
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    clearError();
    if (register && !rules.every((rule) => rule.valid)) {
      setError('Проверьте пароль и его подтверждение.');
      return;
    }
    setBusy(true);
    try {
      onLogin(
        await api<User>(
          register ? '/auth/register' : '/auth/login',
          register
            ? { name: name.trim(), email: email.trim(), password, password_confirmation: confirmation }
            : { email: email.trim(), password },
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось войти');
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <header className="auth-header">
        <div className="auth-brand">
          <img src={logo} alt="" />
          <strong>WareSync</strong>
        </div>
        <span className="auth-local">
          <ShieldCheck size={15} />
          Локальное рабочее пространство
        </span>
      </header>
      <div className="auth-layout">
        <section className="auth-intro">
          <span className="eyebrow">ЗАКУПКИ ПОД КОНТРОЛЕМ</span>
          <h1>
            Ваш склад.
            <br />В одном ритме.
          </h1>
          <p>
            Прогнозируйте спрос, проверяйте рекомендации и принимайте решения в одном рабочем пространстве.
          </p>
          <div className="auth-flow">
            <span>
              <b>01</b>Данные
            </span>
            <ArrowRight size={18} />
            <span>
              <b>02</b>Прогноз
            </span>
            <ArrowRight size={18} />
            <span>
              <b>03</b>Закупка
            </span>
          </div>
          <div className="auth-intro-note">
            <ShieldCheck size={20} />
            <span>
              От исходных данных
              <br />
              до объяснимого решения.
            </span>
          </div>
        </section>
        <section className="auth-card" aria-labelledby="auth-title">
          <div className="auth-tabs">
            <button
              type="button"
              aria-pressed={!register}
              disabled={busy}
              className={!register ? 'active' : ''}
              onClick={() => {
                setRegister(false);
                setPassword('');
                setConfirmation('');
                setError('');
                clearError();
              }}
            >
              Вход
            </button>
            <button
              type="button"
              aria-pressed={register}
              disabled={busy}
              className={register ? 'active' : ''}
              onClick={() => {
                setRegister(true);
                setPassword('');
                setConfirmation('');
                setError('');
                clearError();
              }}
            >
              Регистрация
            </button>
          </div>
          <h2 id="auth-title">{register ? 'Создайте аккаунт' : 'С возвращением'}</h2>
          <p>
            {register
              ? 'Укажите имя, email и придумайте пароль.'
              : 'Войдите, чтобы продолжить работу со складом.'}
          </p>
          <form className="account-form" onSubmit={(event) => void submit(event)}>
            <fieldset disabled={busy}>
              {register && (
                <label>
                  Ваше имя
                  <input
                    autoComplete="name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    minLength={2}
                    maxLength={80}
                    placeholder="Как к вам обращаться"
                  />
                </label>
              )}
              <label>
                Email
                <input
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  maxLength={254}
                  placeholder="you@company.kz"
                />
              </label>
              <label>
                Пароль
                <div className="password-field">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    autoComplete={register ? 'new-password' : 'current-password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={register ? 8 : 1}
                    maxLength={128}
                    aria-describedby={register ? 'password-rules' : undefined}
                    placeholder={register ? 'Минимум 8 символов' : 'Введите пароль'}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                    aria-pressed={showPassword}
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </label>
              {register && (
                <>
                  <label>
                    Повторите пароль
                    <input
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="new-password"
                      value={confirmation}
                      onChange={(e) => setConfirmation(e.target.value)}
                      required
                      maxLength={128}
                      aria-invalid={!!confirmation && confirmation !== password}
                      placeholder="Введите пароль ещё раз"
                    />
                  </label>
                  <ul className="password-rules" id="password-rules" aria-live="polite">
                    {rules.map((rule) => (
                      <li className={rule.valid ? 'valid' : ''} key={rule.text}>
                        <Check size={14} />
                        {rule.text}
                        {rule.valid && <span className="sr-only"> — выполнено</span>}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {(error || initialError) && (
                <div className="account-error" role="alert">
                  {error || initialError}
                </div>
              )}
              <button className="button primary auth-submit" type="submit">
                {busy ? <LoaderCircle className="spin" size={18} /> : <ArrowRight size={18} />}
                {busy ? 'Проверяем…' : register ? 'Создать аккаунт' : 'Войти'}
              </button>
            </fieldset>
          </form>
          <p className="auth-footnote">
            {register
              ? 'Для локального демо подтверждение email не требуется. После регистрации вы сразу войдёте в общее рабочее пространство.'
              : 'Аккаунт хранится на этом сервере. Для входа нужен только email и пароль.'}
          </p>
        </section>
      </div>
      <footer className="auth-footer">
        <span>WareSync · Планируйте уверенно</span>
        <ThemePicker theme={theme} setTheme={setTheme} />
      </footer>
    </main>
  );
}

function AccountPanel({
  user,
  panel,
  setPanel,
  close,
  theme,
  setTheme,
  saved,
  loggedOut,
}: {
  user: User;
  panel: 'profile' | 'settings';
  setPanel: (panel: 'profile' | 'settings') => void;
  close: () => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  saved: (user: User) => void;
  loggedOut: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(user.name);
  const [jobTitle, setJobTitle] = useState(user.job_title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    try {
      saved(await api<User>('/auth/profile', { name: name.trim(), job_title: jobTitle.trim() }));
      setNotice('Профиль сохранён');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить профиль');
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    setBusy(true);
    setError('');
    try {
      await api('/auth/logout', {});
      loggedOut();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось выйти');
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="modal account-modal"
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="modal-header">
        <h2>Ваш аккаунт</h2>
        <button type="button" className="icon-button" aria-label="Закрыть аккаунт" onClick={close}>
          <X size={20} />
        </button>
      </div>
      <div className="account-panel-body">
        <div className="account-identity">
          <span className="account-avatar">{initials(user.name)}</span>
          <div>
            <h3>{user.name}</h3>
            <p>{user.email}</p>
          </div>
        </div>
        <div className="auth-tabs">
          <button
            className={panel === 'profile' ? 'active' : ''}
            aria-pressed={panel === 'profile'}
            onClick={() => setPanel('profile')}
          >
            <UserRound size={16} />
            Профиль
          </button>
          <button
            className={panel === 'settings' ? 'active' : ''}
            aria-pressed={panel === 'settings'}
            onClick={() => setPanel('settings')}
          >
            <Sun size={16} />
            Настройки
          </button>
        </div>
        {panel === 'profile' ? (
          <form className="account-form" onSubmit={(event) => void save(event)}>
            <fieldset disabled={busy}>
              <label>
                Имя
                <input
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    setNotice('');
                  }}
                  autoComplete="name"
                  required
                  minLength={2}
                  maxLength={80}
                />
              </label>
              <label>
                Должность
                <input
                  value={jobTitle}
                  onChange={(e) => {
                    setJobTitle(e.target.value);
                    setNotice('');
                  }}
                  autoComplete="organization-title"
                  maxLength={80}
                  placeholder="Например, менеджер закупок"
                />
              </label>
              <label>
                Email
                <input type="email" value={user.email} readOnly />
              </label>
              <p className="account-hint">
                <ShieldCheck size={15} />
                Вход по паролю · общее рабочее пространство
              </p>
              <button className="button primary" type="submit">
                {busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}Сохранить профиль
              </button>
            </fieldset>
          </form>
        ) : (
          <section className="appearance-settings">
            <h3>Оформление</h3>
            <p>Выберите комфортную тему интерфейса.</p>
            <ThemePicker theme={theme} setTheme={setTheme} />
            <p className="account-hint">
              Сохраняется на этом устройстве. Системная тема следует настройкам устройства.
            </p>
          </section>
        )}
        {error && (
          <p className="account-error" role="alert">
            {error}
          </p>
        )}
        {notice && panel === 'profile' && (
          <p className="account-success" role="status">
            <Check size={16} />
            {notice}
          </p>
        )}
        <div className="account-panel-footer">
          <span>С нами с {new Date(user.created_at).toLocaleDateString('ru-RU')}</span>
          <button type="button" className="button secondary" disabled={busy} onClick={() => void logout()}>
            <LogOut size={16} />
            Выйти
          </button>
        </div>
      </div>
    </dialog>
  );
}

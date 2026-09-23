import { createRoot } from 'react-dom/client';
import App from './App';
import { AccountRoot, applyTheme, savedTheme } from './Account';
import './styles.css';
import './account.css';

applyTheme(savedTheme());
createRoot(document.getElementById('root')!).render(
  <AccountRoot>
    <App />
  </AccountRoot>,
);

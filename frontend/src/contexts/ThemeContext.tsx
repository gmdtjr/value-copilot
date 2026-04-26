import { createContext, useContext, useEffect, useState } from 'react'

type Theme = 'dark' | 'light'
export type FontSize = 'sm' | 'md' | 'lg'

interface ThemeContextValue {
  theme: Theme
  toggleTheme: () => void
  fontSize: FontSize
  setFontSize: (s: FontSize) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() =>
    (localStorage.getItem('theme') as Theme) ?? 'dark'
  )
  const [fontSize, setFontSizeState] = useState<FontSize>(() =>
    (localStorage.getItem('fontSize') as FontSize) ?? 'md'
  )

  useEffect(() => {
    const html = document.documentElement
    if (theme === 'dark') html.classList.add('dark')
    else html.classList.remove('dark')
    localStorage.setItem('theme', theme)
  }, [theme])

  function toggleTheme() {
    setTheme(t => (t === 'dark' ? 'light' : 'dark'))
  }

  function setFontSize(s: FontSize) {
    setFontSizeState(s)
    localStorage.setItem('fontSize', s)
  }

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, fontSize, setFontSize }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}

import { Sun, Moon } from 'lucide-react'
import { useTheme, type FontSize } from '../contexts/ThemeContext'

const FONT_SIZES: { value: FontSize; label: string; style: string }[] = [
  { value: 'sm', label: 'A', style: 'text-[11px]' },
  { value: 'md', label: 'A', style: 'text-[13px]' },
  { value: 'lg', label: 'A', style: 'text-[16px]' },
]

export function ThemeControls() {
  const { theme, toggleTheme, fontSize, setFontSize } = useTheme()

  return (
    <div className="flex items-center gap-1">
      {/* Font size selector */}
      <div className="hidden sm:flex items-center border border-gray-300 dark:border-gray-700 rounded-lg overflow-hidden">
        {FONT_SIZES.map(({ value, label, style }) => (
          <button
            key={value}
            onClick={() => setFontSize(value)}
            title={`글자 크기: ${value === 'sm' ? '작게' : value === 'md' ? '보통' : '크게'}`}
            className={`px-2 py-1 transition-colors leading-none ${style} ${
              fontSize === value
                ? 'bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white font-semibold'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Theme toggle */}
      <button
        onClick={toggleTheme}
        title={theme === 'dark' ? '라이트 모드' : '다크 모드'}
        className="flex items-center justify-center w-8 h-8 rounded-lg transition-colors text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800"
      >
        {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
      </button>
    </div>
  )
}

/* eslint-disable @typescript-eslint/no-explicit-any */
if (typeof (globalThis as any).__publicField === 'undefined') {
  ;(globalThis as any).__publicField = (obj: any, key: any, value: any) => {
    if (typeof key !== 'symbol') key = key + ''
    if (key in obj)
      Object.defineProperty(obj, key, {
        enumerable: true,
        configurable: true,
        writable: true,
        value,
      })
    else obj[key] = value
    return value
  }
}
/* eslint-enable @typescript-eslint/no-explicit-any */

import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './App.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

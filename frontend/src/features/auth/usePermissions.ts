import { useAuth } from './useAuth'

/**
 * Returns `can(module, action)` for showing or hiding parts of the screen.
 * This is a convenience only: the server checks every request again.
 */
export function useCan(): (module: string, action: string) => boolean {
  const { state } = useAuth()
  const permissions = state.status === 'signed-in' ? state.permissions : {}
  return (module, action) => Boolean(permissions[module]?.[action])
}

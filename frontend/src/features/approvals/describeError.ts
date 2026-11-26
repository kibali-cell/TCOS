import { ApiError, fieldErrors } from '../../lib/api'

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(fieldErrors(error)).flat()
    return details.length > 0 ? details.join(' ') : error.message
  }
  return 'Something went wrong. Please try again.'
}

import { Link } from 'react-router-dom'

export function Forbidden() {
  return (
    <>
      <h1>No access</h1>
      <p role="alert">You do not have permission to open this page.</p>
      <p>
        <Link to="/">Return to the dashboard</Link>
      </p>
    </>
  )
}

/** The twelve institutional modules. Navigation entries only: none of them is
 *  built yet, and each one says so plainly instead of showing a fake screen. */
export interface ModuleInfo {
  slug: string
  name: string
  /** The backend permission module that controls whether this entry is shown. */
  permission: string
}

export const MODULES: readonly ModuleInfo[] = [
  { slug: 'administration', permission: 'administration', name: 'Institutional Administration' },
  { slug: 'social-welfare', permission: 'social_welfare', name: 'Social Welfare Management' },
  { slug: 'child-profiles', permission: 'children', name: 'Child Profile Management' },
  { slug: 'education', permission: 'education', name: 'Education Management' },
  { slug: 'medical', permission: 'medical', name: 'Medical Management' },
  { slug: 'finance', permission: 'finance', name: 'Financial Management' },
  { slug: 'projects', permission: 'projects', name: 'Project Management' },
  { slug: 'human-resources', permission: 'hr', name: 'Human Resources' },
  { slug: 'procurement', permission: 'procurement', name: 'Procurement' },
  { slug: 'stores', permission: 'stores', name: 'Stores and Inventory' },
  { slug: 'donors', permission: 'donors', name: 'Donor Management' },
  { slug: 'reports', permission: 'reports', name: 'Reports and Analytics' },
]

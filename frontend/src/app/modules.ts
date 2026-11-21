/** The twelve institutional modules. Navigation entries only: none of them is
 *  built yet, and each one says so plainly instead of showing a fake screen. */
export interface ModuleInfo {
  slug: string
  name: string
}

export const MODULES: readonly ModuleInfo[] = [
  { slug: 'administration', name: 'Institutional Administration' },
  { slug: 'social-welfare', name: 'Social Welfare Management' },
  { slug: 'child-profiles', name: 'Child Profile Management' },
  { slug: 'education', name: 'Education Management' },
  { slug: 'medical', name: 'Medical Management' },
  { slug: 'finance', name: 'Financial Management' },
  { slug: 'projects', name: 'Project Management' },
  { slug: 'human-resources', name: 'Human Resources' },
  { slug: 'procurement', name: 'Procurement' },
  { slug: 'stores', name: 'Stores and Inventory' },
  { slug: 'donors', name: 'Donor Management' },
  { slug: 'reports', name: 'Reports and Analytics' },
]

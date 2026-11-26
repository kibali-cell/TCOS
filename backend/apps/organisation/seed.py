"""Initial, editable organisation structure (PROPOSAL, see DECISIONS D-055).

One department per module of the system, each with a head position, and an Executive
Director position that the heads report to. No people are created. Everything here can be
renamed, rearranged or archived from the Organisation screen.

Safe to repeat: a department is created only if its code is missing (and its name is
free), and positions are added only to departments created by this run, so an
administrator's later edits are never undone.
"""

EXECUTIVE_DIRECTOR = "Executive Director"

# (code, name, description, head position title)
DEPARTMENTS = (
    (
        "ADMINISTRATION",
        "Institutional Administration",
        "Leadership, governance and administration of the institution.",
        EXECUTIVE_DIRECTOR,
    ),
    (
        "SOCIAL_WELFARE",
        "Social Welfare",
        "Family tracing, case management and outreach.",
        "Head of Social Welfare",
    ),
    (
        "CHILD_PROFILES",
        "Child Profiles",
        "Records of each child in residential and outreach care.",
        "Head of Child Profiles",
    ),
    ("EDUCATION", "Education", "Schooling and learning support.", "Head of Education"),
    ("MEDICAL", "Medical", "Health care and medical records.", "Head of Medical"),
    ("FINANCE", "Finance", "Budgets, payments, accounts and reporting.", "Head of Finance"),
    ("PROJECTS", "Projects", "Planning and delivery of projects.", "Head of Projects"),
    (
        "HUMAN_RESOURCES",
        "Human Resources",
        "Staff records, contracts and leave.",
        "Head of Human Resources",
    ),
    (
        "PROCUREMENT",
        "Procurement",
        "Purchasing and supplier management.",
        "Head of Procurement",
    ),
    (
        "STORES",
        "Stores and Inventory",
        "Stock, supplies and equipment.",
        "Head of Stores",
    ),
    (
        "DONORS",
        "Donor Relations",
        "Donors, grants and supporter communication.",
        "Head of Donor Relations",
    ),
    (
        "REPORTS",
        "Reports and Analytics",
        "Institutional reporting and analysis.",
        "Head of Reports and Analytics",
    ),
)


def seed(Department, Position) -> int:
    """Create what is missing. Returns the number of departments created."""
    created = []
    for code, name, description, head_title in DEPARTMENTS:
        if Department.objects.filter(code=code).exists():
            continue
        if Department.objects.filter(name=name).exists():
            continue
        department = Department.objects.create(code=code, name=name, description=description)
        Position.objects.create(
            department=department, title=head_title, is_department_head_position=True
        )
        created.append(department)

    director = Position.objects.filter(
        department__code="ADMINISTRATION", title=EXECUTIVE_DIRECTOR, is_archived=False
    ).first()
    if director is not None:
        for department in created:
            if department.code == "ADMINISTRATION":
                continue
            Position.objects.filter(department=department, is_department_head_position=True).update(
                reports_to=director
            )
    return len(created)

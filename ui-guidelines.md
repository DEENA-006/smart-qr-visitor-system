# Premium UI/UX Design Guidelines
## Smart QR Visitor Management System

## 1. Design Vision

Build a premium, production-quality web application for intelligent visitor management in colleges, universities, offices, and institutional campuses.

The website must look and feel like a modern SaaS product, not a basic HTML administration panel or a generic dashboard template.

The interface should communicate:
- Trust and security
- Intelligence and efficiency
- Professionalism
- Precision and reliability
- Modern technology
- Ease of use

The visual experience should be comparable in polish to contemporary enterprise software such as Linear, Stripe Dashboard, and modern B2B SaaS applications, while maintaining an original design identity.

Do not copy another product's interface exactly.

### Core design principles

1. Strong visual hierarchy.
2. Generous but purposeful spacing.
3. Sophisticated typography.
4. Refined surfaces, borders, and shadows.
5. Consistent component design.
6. Subtle, meaningful animations.
7. High information density without clutter.
8. Excellent desktop and mobile responsiveness.
9. Real database-driven information.
10. Accessibility and usability without sacrificing aesthetics.

The finished website should look impressive during a project demonstration and remain practical for everyday reception and campus security operations.

---

## 2. Brand Identity

### Product name

Smart Visitor

### Supporting tagline

Secure Entry. Smarter Access.

The application may display the full name "Smart QR Visitor Management System" in the login page, branding area, and documentation. Use "Smart Visitor" in compact navigation areas.

### Brand personality

- Modern
- Reliable
- Intelligent
- Professional
- Minimal
- Security-focused

### Logo direction

Create a simple, original vector-style brand mark combining a shield, doorway, checkmark, or QR-inspired geometric pattern.

The logo must remain legible at small sizes. Avoid complicated illustrations, generic emoji logos, and oversized decorative graphics.

Use SVG or CSS-based visual elements when practical.

### Iconography

Use a consistent line-icon library such as Lucide.

Recommended icons include:
- LayoutDashboard
- Users
- UserRoundCheck
- ClipboardList
- QrCode
- ScanLine
- ShieldCheck
- Building2
- Clock
- CalendarDays
- ChartNoAxesCombined
- Settings
- FileText
- Search
- Bell
- CircleHelp
- LogOut

Use consistent icon sizes, stroke weights, and alignment. Do not mix unrelated icon styles.

---

## 3. Visual Design Language

Adopt a refined enterprise dashboard aesthetic with a light default theme.

### Primary visual characteristics

- Soft neutral application background.
- Crisp white content surfaces.
- Deep navy text.
- Rich but restrained blue primary actions.
- Thin, subtle borders.
- Layered shadows used sparingly.
- Carefully rounded cards and controls.
- Clean data visualizations.
- Generous spacing around important content.
- Small, consistent status indicators.
- Elegant typography and numerical metrics.

Avoid a visually flat interface where every section looks identical. Create hierarchy through spacing, typography, surface contrast, alignment, and selective emphasis.

Do not place every element inside a card. Use open layouts and whitespace where appropriate.

### Design tokens

Define all reusable visual values centrally in CSS custom properties.

:root {
  color-scheme: light;

  --color-primary: #3157D5;
  --color-primary-hover: #2446B8;
  --color-primary-soft: #EDF2FF;

  --color-background: #F5F7FB;
  --color-surface: #FFFFFF;
  --color-surface-secondary: #F8FAFD;
  --color-surface-hover: #F1F5F9;

  --color-text: #172033;
  --color-text-secondary: #536178;
  --color-text-muted: #78859A;

  --color-border: #E4E9F1;
  --color-border-strong: #D4DCE8;

  --color-success: #16794A;
  --color-success-soft: #E8F7EF;

  --color-warning: #A9630B;
  --color-warning-soft: #FFF4DE;

  --color-danger: #C43D4B;
  --color-danger-soft: #FDECEF;

  --color-info: #2865C7;
  --color-info-soft: #EAF2FF;

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;

  --shadow-card:
    0 1px 3px rgba(18, 35, 66, 0.04),
    0 4px 16px rgba(18, 35, 66, 0.025);

  --shadow-dropdown:
    0 12px 32px rgba(18, 35, 66, 0.12);

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;

  --sidebar-width: 252px;
  --topbar-height: 72px;
}

These values are starting points. Refine them consistently while maintaining a cohesive design system.

Do not introduce arbitrary colors, radii, shadows, or spacing values throughout individual pages.

---

## 4. Typography System

Typography must contribute significantly to the premium appearance.

Use a modern sans-serif font such as Inter or Geist, with a suitable system-font fallback.

If an external font is unavailable, the website must still render correctly.

### Typography hierarchy

- Main page heading: approximately 28–32px, semibold.
- Section heading: approximately 18–22px, semibold.
- Card heading: approximately 15–17px, semibold.
- Body text: approximately 14–16px.
- Supporting text: approximately 13–14px.
- Form labels: approximately 13–14px, medium.
- Table content: approximately 13–14px.
- Compact metadata: approximately 12–13px.

Use line height, font weight, and spacing to establish hierarchy instead of using oversized headings everywhere.

### Numerical typography

Use tabular numerals for:
- Visitor counts
- Dates and times
- Report totals
- Duration values
- Dashboard metrics

Important metrics should be easy to scan at a glance.

Avoid excessive uppercase text, tiny text, and low-contrast labels.

---

## 5. Application Shell

Create a polished application shell shared across all staff pages.

### Desktop layout

Use three primary interface regions:

1. Persistent left sidebar.
2. Top navigation bar.
3. Main content canvas.

### Sidebar

The sidebar should:
- Have a refined white or near-white surface.
- Display the brand mark and application name.
- Group navigation items logically.
- Use consistent icon alignment.
- Clearly indicate the active route.
- Support a compact or collapsed state when appropriate.
- Keep the logout and account actions near the bottom.
- Include subtle hover transitions.
- Avoid excessive dividers and unnecessary decoration.

Active navigation should use a soft blue background, stronger text, and a restrained indicator.

Suggested navigation groups:

WORKSPACE
- Overview
- Visitor Requests
- Visitors
- QR Scanner
- Live Occupancy

MANAGEMENT
- Registration Forms
- Faculty and Staff
- Departments
- Reports

SECURITY AND SETTINGS
- Emergency List
- Audit Logs
- Settings

Show only the items authorized for the current role. Do not simply hide links while leaving their backend routes accessible.

### Top navigation bar

Include:
- Current page title or breadcrumb.
- Global search where useful.
- Notification indicator if notifications are implemented.
- Help or support link if available.
- User avatar or initials.
- User name and role.
- Account dropdown.

Use a subtle bottom border. Avoid a large decorative header that consumes too much vertical space.

### Main content area

- Use a consistent maximum width where appropriate.
- Maintain 24–32px desktop page padding.
- Keep headings, descriptions, filters, and actions aligned.
- Use consistent spacing between page sections.
- Let data tables and wide operational views use available width.
- Avoid unnecessary horizontal scrolling.

---

## 6. Premium Login Experience

The login page should look like an intentional product entry point.

### Layout

Create a balanced split-screen design on desktop.

Left panel:
- Product logo and name.
- Strong heading such as "A smarter way to manage campus access."
- Short supporting description.
- A tasteful abstract illustration inspired by secure access, QR scanning, or connected campus operations.
- A subtle brand-colored background or carefully controlled visual treatment.

Right panel:
- Clean login form.
- Welcome heading.
- Username or email field.
- Password field.
- Show/hide password control.
- Remember-me option only if implemented securely and appropriately.
- Primary sign-in button.
- Accessible error feedback.
- Minimal footer.

On mobile, collapse the split-screen layout into a compact, focused login experience.

### Interaction details

- Focused inputs receive a clear border and focus ring.
- Password visibility can be toggled.
- The submit button displays a loading state.
- Repeated submission is prevented while authentication is processing.
- Authentication failures use a generic safe message.
- No account enumeration through different error messages.
- Never display demo passwords or production credentials.

Avoid an oversized glassmorphism card floating over a gradient background. Prefer crisp surfaces, strong alignment, and deliberate whitespace.

---

## 7. Admin Dashboard

The Admin dashboard must look like a polished operational command center.

### Page header

Title: "Overview"

Supporting text: "Monitor visitor activity and manage campus access."

Include:
- Current date or selected reporting period.
- Date range selector.
- Relevant quick action.
- Refresh action if live refresh is supported.

### KPI section

Use a responsive grid of four or five metric cards.

Recommended metrics:
1. Total visit requests.
2. Pending approvals.
3. Approved visits.
4. Currently recorded active visitors.
5. Completed visits.

Each metric card should contain:
- Short, meaningful label.
- Prominent numeric value.
- Small supporting icon.
- Optional comparison against a valid previous period.
- Optional contextual description.

Use restrained color accents. Do not give every card a different bright background.

Trend indicators must be calculated from real data using clearly defined comparison periods. If no comparison is available, omit the trend.

### Main dashboard sections

Create a balanced two-column layout where space allows.

Left:
- Visitor activity chart.
- Recent visit requests or visit events.

Right:
- Pending approvals summary.
- Visit status distribution.
- Quick actions.

Use a single strong visual anchor rather than many equally prominent charts.

### Quick actions

Examples:
- Create Registration Form
- Manage Staff
- View Visitors
- Open Reports

Use compact, well-designed action cards or buttons.

### Recent activity

Display:
- Visitor or record reference.
- Event type.
- Responsible staff member where authorized.
- Timestamp.
- Status.

Provide useful empty states when no events exist.

Never use static sample numbers as live dashboard metrics.

---

## 8. Faculty Dashboard

Design the Faculty dashboard around decisions and upcoming appointments.

### Main sections

- Requests awaiting my approval.
- Upcoming visits.
- Recently reviewed requests.
- Search and filtering.
- Form customization, only when authorized.

### Approval interface

Each request should show relevant information such as:
- Visitor name.
- Visit purpose.
- Planned visit time.
- Organization.
- Reference number.
- Current status.

Provide clear Approve and Reject actions.

Use a confirmation dialog or reason field where required.

### Interaction rules

- Disable the action while the server is processing it.
- Display the result only after server confirmation.
- Preserve the request if an action fails.
- Explain authorization errors without exposing internal details.
- Never let a Faculty user approve a request assigned to another approver unless the policy explicitly permits it.

---

## 9. Security Operations Dashboard

This page has a different purpose from the administrative dashboard. Optimize it for speed, clarity, and accurate decisions.

### Visual priority

1. Scan QR.
2. Validate or look up a visit.
3. Confirm identity.
4. Check in or check out.
5. View current recorded occupancy.
6. Access emergency visitor information.

### Layout

Use a clear operational layout with:
- A prominent scanner action.
- Manual reference lookup.
- Current occupancy metric.
- Recent gate activity.
- Active visitor table.
- Quick access to the emergency list.

Keep critical actions visible without forcing security staff to navigate through several dashboard pages.

### QR scanner interface

When scanning is activated, display:
- A clear camera/scanner region.
- Instructions for positioning the QR code.
- Camera permission feedback.
- A manual lookup fallback.
- A cancel or close action.

Handle unavailable cameras and denied permissions gracefully.

Do not depend on camera scanning alone; provide an authorized manual lookup workflow.

### Validation result states

Use distinct layouts or status panels for:

- Valid and eligible.
- Verification required.
- Expired.
- Revoked.
- Not approved.
- Already checked in.
- Already checked out.
- Unknown credential.
- Server unavailable.

Each result should contain:
- Clear status text.
- A suitable icon.
- A brief explanation.
- The next permitted action, if any.

A QR scan must never be treated as proof of identity. The application must require the configured identity verification process before confirming entry.

Only display a successful check-in after the backend has committed the operation.

### Occupancy indicator

Display the number of recorded active visits prominently.

Label it accurately as "Currently Checked In" or "Recorded Occupancy."

Do not claim that this count guarantees the number of people physically present.

---

## 10. Dynamic Registration Form Builder

The form builder is a major feature and deserves a dedicated, high-quality interface.

### Layout

Use a three-panel editor on sufficiently wide screens.

Left panel:
- Field palette.
- Available field types.
- Field insertion actions.

Center panel:
- Live form preview.
- Field ordering.
- Drag-and-drop reordering when supported.
- Visual representation of the visitor-facing form.

Right panel:
- Selected field settings.
- Label.
- Help text.
- Required toggle.
- Options.
- Supported validation settings.
- Access and visibility settings where authorized.

On tablet and mobile, replace the three-panel layout with tabs, drawers, or a focused single-panel editor.

### Header actions

Include:
- Form name.
- Visit type.
- Draft or Published status.
- Save Draft.
- Preview.
- Publish.

Clearly distinguish saving a draft from publishing a new version.

### Field palette

Provide polished field controls for:
- Short text.
- Long text.
- Telephone.
- Email.
- Date.
- Time.
- Dropdown.
- Checkbox.
- Vehicle registration when permitted.

Each field type should have a small icon, label, and concise description.

### Live preview

The preview should resemble the actual public registration page.

Include:
- Realistic labels.
- Required indicators.
- Help text.
- Appropriate spacing.
- Grouped fields.
- Example placeholder text.

Clearly label preview-only content. Never submit preview data as a real visitor registration.

### Form configuration safeguards

- Only authorized Admin users can publish global form policies.
- Faculty customization must respect administrator-defined limits.
- Use validated supported field types.
- Never execute arbitrary user-provided expressions.
- Create a new version when changing a published form.
- Validate submitted values on the server.

---

## 11. Visitor Registration Experience

The visitor-facing registration page should be welcoming, simple, and mobile-first.

### Design direction

Use a focused single-column form with a clear heading and a short explanation.

Avoid presenting visitors with an internal staff dashboard or an excessively complicated multi-step wizard.

### Recommended layout

1. Brand header.
2. Page title: "Visitor Registration."
3. Short instructions.
4. Visit details section.
5. Visitor information section.
6. Additional configured fields.
7. Privacy notice.
8. Submit button.
9. Compact footer.

Use section groupings only when they improve readability.

### Form behavior

- Display required fields clearly.
- Use the correct input type for each field.
- Show validation messages near the affected input.
- Preserve safe field values after validation errors.
- Prevent repeated submissions while processing.
- Display a clear success or error state.

### Submission confirmation

After successful registration, display:
- Confirmation message.
- Unique reference number.
- Current approval status.
- Next-step instructions.
- Expected appointment details where appropriate.

Do not generate or show an approved visit QR credential before the required approval and credential-issuance workflow succeeds.

Include a short privacy notice explaining why information is collected and how it is used.

---

## 12. Visitor Management Tables

Tables must look polished and remain usable with many records.

### Table design

- Clear column headers.
- Consistent row height.
- Subtle horizontal separators.
- Comfortable cell padding.
- Aligned numeric values.
- Restrained status badges.
- Hover highlighting.
- Pagination.
- Search and filters.
- Sort controls where implemented.

Avoid excessive borders around every cell.

### Recommended visitor columns

- Visitor.
- Visit reference.
- Host or department.
- Scheduled time.
- Status.
- Check-in time.
- Actions.

Choose columns according to the current role and page.

### Search and filters

Include:
- Search field with a search icon.
- Status filter.
- Date range.
- Host or department filter where authorized.
- Clear filters action.

Filters must query the backend rather than filtering only the currently displayed rows when the dataset is paginated.

### Row actions

Use a compact action menu for secondary actions.

Make important actions visible.

Use confirmation dialogs for destructive or sensitive operations.

### Empty state

When no records match the search, show:
- A simple icon or illustration.
- "No visitors found."
- A helpful explanation.
- A clear action to reset filters or create a new record, if authorized.

Do not leave the page as a blank table.

---

## 13. Reports and Analytics

The reports section should feel like a professional business intelligence interface without unnecessary complexity.

### Report header

Include:
- Report title.
- Date range.
- Relevant filters.
- Export action.
- Last-updated information when meaningful.

### Visualizations

Use charts only when they communicate meaningful information.

Suitable examples:
- Visits over time.
- Visits by status.
- Visits by department.
- Peak arrival periods.
- Average recorded visit duration.

Every chart must use real database data.

### Chart styling

- Use a restrained palette.
- Keep gridlines subtle.
- Label axes clearly.
- Include useful tooltips.
- Provide a meaningful empty state.
- Ensure charts work on smaller screens.
- Provide a text or tabular alternative for accessibility.

### Export experience

- Explain which filters will apply to the export.
- Show loading and success feedback.
- Respect role permissions.
- Escape CSV content safely.
- Protect against spreadsheet formula injection.
- Do not expose unauthorized contact details.

---

## 14. Emergency Visitor List

Treat the emergency view as a high-priority operational interface rather than an ordinary report.

### Design requirements

- Clear "Emergency Visitor List" heading.
- Current recorded active visitor count.
- Last refresh timestamp.
- Readable visitor list.
- Visitor name and reference.
- Recorded check-in time.
- Host or department when available.
- Data-quality warnings.

Highlight:
- Missing checkout records.
- Stale data.
- Pending synchronization.
- Incomplete or uncertain records.

Use a clear refresh indicator.

Restrict access to authorized staff and record sensitive access in the audit log where required.

Do not imply that digital records alone can guarantee a complete physical headcount.

---

## 15. Reusable Component System

Build a consistent library of reusable interface components.

### Core components

- AppSidebar
- AppHeader
- PageHeader
- Breadcrumbs
- MetricCard
- PrimaryButton
- SecondaryButton
- IconButton
- SearchInput
- FilterBar
- DataTable
- Pagination
- StatusBadge
- FormField
- SelectField
- DateRangePicker
- Modal
- ConfirmationDialog
- ToastNotification
- EmptyState
- LoadingState
- ErrorState
- SkeletonLoader
- QRScannerPanel
- QRValidationResult
- VisitorProfileSummary
- ActivityTimeline

### Component rules

- Use consistent spacing and typography.
- Use shared design tokens.
- Support keyboard interaction.
- Provide clear disabled and loading states.
- Keep props and responsibilities focused.
- Avoid duplicating markup across dashboards.
- Ensure each component behaves correctly on mobile.
- Avoid adding unnecessary component abstractions for one-off elements.

Use a small, coherent component system rather than a different design on every page.

---

## 16. Motion and Micro-Interactions

Animations should add refinement and clarity, not distract from operational tasks.

### Recommended interactions

- Short sidebar active-state transitions.
- Subtle button hover and press feedback.
- Smooth dropdown opening.
- Small modal fade or scale transitions.
- Table-row hover states.
- Loading indicators.
- Toast entrance and dismissal.
- Gentle focus transitions.

### Motion guidelines

- Prefer transitions around 120–220 milliseconds.
- Use simple easing curves.
- Avoid excessive parallax, bouncing, and large animated backgrounds.
- Avoid blocking essential actions with animation.
- Respect the user's reduced-motion preference.

Do not add animations merely to make the application appear more complex.

---

## 17. Feedback and System States

Every operation that communicates with the backend must handle its complete lifecycle.

### Loading

Use:
- Button loading indicators.
- Skeletons for larger data sections.
- Small inline spinners for lightweight actions.

Avoid replacing the entire page with a spinner when only one component is loading.

### Success

Use clear messages such as:
- "Visit request submitted successfully."
- "Request approved."
- "Check-in recorded."
- "Checkout completed."
- "Form version published."

Show these only after the backend confirms success.

### Errors

Use understandable messages such as:
- "This QR credential has expired."
- "You do not have permission to perform this action."
- "The server could not confirm the operation. Please check the visit status before retrying."

Do not expose SQL errors, stack traces, internal paths, or secret values.

### Confirmation

Use confirmation dialogs for:
- Rejecting a visit where confirmation is required.
- Revoking a QR credential.
- Deactivating a staff account.
- Publishing a form version.
- Performing administrative corrections.

Do not add unnecessary confirmation dialogs to every harmless action.

---

## 18. Responsive Design

Design mobile-first and progressively enhance the interface.

### Small mobile: up to 480px

- Single-column layouts.
- Compact page headings.
- Full-width primary actions when useful.
- Collapsible navigation.
- Touch-friendly controls.
- Responsive tables or stacked record cards.
- No accidental horizontal overflow.

### Tablet: 481px–768px

- Compact sidebar or drawer.
- Two-column metric cards where space permits.
- Adaptive forms and tables.
- Simplified form-builder layout.

### Desktop: 769px–1199px

- Full application shell.
- Responsive metric grid.
- Sidebar navigation.
- Multi-column forms and dashboard sections.

### Large desktop: 1200px and above

- Full sidebar.
- Balanced content width.
- Expanded tables and dashboards.
- Multi-panel form builder where useful.

### Touch targets

Aim for approximately 44px high touch targets for primary interactive controls, with adequate spacing between adjacent actions.

Responsive behavior must be tested at actual viewport sizes, not inferred from desktop appearance.

---

## 19. Accessibility and Inclusive Design

Follow semantic HTML and WCAG-aligned accessibility practices.

Requirements:
- Visible keyboard focus.
- Correct label and input associations.
- Sufficient contrast.
- Keyboard-operable dropdowns and dialogs.
- Accessible error messages.
- Appropriate accessible names for icon-only buttons.
- Logical heading hierarchy.
- Screen-reader-friendly status changes.
- Reduced-motion support.
- Camera-independent scanning fallback.
- No information conveyed solely through color.

Do not sacrifice accessibility for visual minimalism.

---

## 20. Frontend Engineering Standards

- Use reusable Jinja2 templates and shared layouts.
- Keep CSS organized and reusable.
- Prefer CSS variables over repeated hard-coded values.
- Separate page-specific JavaScript from shared utilities.
- Avoid excessive inline CSS and inline JavaScript.
- Do not manipulate sensitive application state exclusively in the browser.
- Keep secrets and authorization logic on the server.
- Use safe template escaping.
- Avoid injecting untrusted HTML.
- Ensure all forms include appropriate CSRF protection.
- Provide a working error page for unexpected failures.
- Keep the UI consistent with the actual backend state.

Use HTML, CSS, JavaScript, Flask, and Jinja2 as the project's agreed stack. Do not introduce a major frontend framework without approval.

---

## 21. Data Integrity and Visual Honesty

The UI must never suggest that an operation succeeded when it has not.

Examples:
- A QR scan is not a confirmed check-in.
- A registration submission is not an approval.
- A pending offline event is not a verified entry.
- A recorded occupancy count is not guaranteed physical occupancy.
- A notification request is not proof of delivery.

Show pending, confirmed, failed, and unverified states accurately.

Never use fabricated analytics, fake visitor records, fake activity feeds, or decorative statistics in the production interface.

If development seed data is used, clearly separate it from real operational data.

---

## 22. Performance and Polish

The website must feel fast and responsive.

- Load only the assets needed by each page.
- Avoid unnecessarily large image files.
- Minimize blocking JavaScript.
- Use pagination for large data collections.
- Avoid reloading the entire page when a focused update is sufficient and safe.
- Provide feedback for slow requests.
- Prevent duplicate form submissions.
- Avoid layout shifts when data loads.
- Use efficient database-backed filters and queries.

Do not sacrifice security or correctness for animation or perceived speed.

---

## 23. Implementation and Verification Process

Before designing a page:
1. Read the project requirements and architecture.
2. Identify the intended user role.
3. Identify the data the page requires.
4. Identify authorized actions.
5. Design the loading, empty, error, and success states.
6. Implement the UI with reusable components.
7. Connect it to real backend functionality.
8. Verify responsive behavior.
9. Test keyboard accessibility.
10. Verify authorization and server-confirmed results.

Do not build the entire application as one giant page.

Develop and verify the login, application shell, and role-based dashboards first. Continue with the form builder, visitor workflows, QR scanning, and reports in separate milestones.

---

## 24. Final Visual Acceptance Criteria

The application is ready for demonstration only when:

- The design has a distinct and consistent visual identity.
- The login page looks polished and intentional.
- Dashboards have clear visual hierarchy.
- Sidebar, header, tables, forms, and dialogs share consistent styling.
- Important information is easy to scan.
- The registration form looks professional on mobile.
- The form builder is intuitive and visually organized.
- QR validation results are clear and unambiguous.
- Loading, empty, error, success, and pending states are implemented.
- All primary actions work with the backend.
- Dashboard metrics and reports use actual database data.
- Role-based access is enforced by the backend.
- The application works at mobile, tablet, and desktop widths.
- Keyboard accessibility and readable contrast are verified.
- No major page relies on generic placeholder layouts.
- No fake operational statistics remain.
- Automated tests cover critical workflows.

## Final Instruction to the AI Developer

Build this application as a cohesive, premium-quality enterprise SaaS product.

Prioritize an elegant visual identity, polished spacing, excellent typography, refined components, thoughtful micro-interactions, responsive layouts, and clear operational workflows.

Do not settle for a generic Bootstrap-looking dashboard, unstyled forms, repetitive white cards, or a collection of disconnected pages.

Every screen must look intentionally designed, but visual polish must never compromise accessibility, data privacy, security, or functional correctness.

Inspect the implemented pages, compare them against these guidelines, and refine inconsistencies before declaring the UI complete.

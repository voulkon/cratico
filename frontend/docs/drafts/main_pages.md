# Frontend Routes & Entity Navigation Map

## All Routes

| # | Route | Page Component | Entity Type | ID Field | Notes |
|---|-------|---------------|-------------|----------|-------|
| 1 | `/` | `HomePage` | — | — | Dashboard |
| 2 | `/search?q=` | `SearchResults` | all types | — | Global search |
| 3 | `/entity/organization/:id` | `EntityDetailPage` | `organization` | `id` (UID) | |
| 4 | `/entity/signer/:id` | `EntityDetailPage` | `signer` | `id` (UID) | |
| 5 | `/entity/unit/:id` | `EntityDetailPage` | `unit` | `id` (UID) | |
| 6 | `/entity/afm/:afm` | `AFMEntityDetailPage` | `company` | `afm` (tax ID) | Separate page component |
| 7 | `/decision/:ada` | `DecisionDetailPage` | `document` | `ada` | |
| 8 | `/person/:personName` | `PersonPage` | `company_person` | URL-encoded name | |
| 9 | `/relationship/entity/:afm/org/:orgUid` | `RelationshipDetailPage` | relationship | `afm` + `orgUid` | Company↔Org pair |
| 10 | `/organizations?uid=` | `OrganizationsPage` | `organization` | `uid` (query) | Org chart |
| 11 | `/library` | `LibraryPage` | bookmark | — | User bookmarks |
| 12 | `/batch/:batchId` | `NotificationBatchDetailPage` | `notification_batch` | `batchId` | |
| 13 | `/notifications/subscriptions/:subId/history` | `SubscriptionHistoryPage` | `notification_subscription` | `subId` | |
| 14 | `/verify-email?token=` | `VerifyEmailPage` | — | `token` (query) | |
| 15 | `/reset-password?token=` | `PasswordResetPage` | — | `token` (query) | |
| 16 | `/legal/:type` | `LegalPage` | `legal_doc` | `type` slug | terms, privacy, etc. |
| 17 | `/health` | `Clock` | — | — | Health check |

## Core Entity Navigations (from `SearchResults.js`)

| Entity Type | `navigate()` call | Page Component |
|---|---|---|
| `organization` | `/entity/organization/${item.id}` | `EntityDetailPage` |
| `signer` | `/entity/signer/${item.id}` | `EntityDetailPage` |
| `unit` | `/entity/unit/${item.id}` | `EntityDetailPage` |
| `company` | `/entity/afm/${item.afm}` | `AFMEntityDetailPage` |
| `company_person` | `/person/${encodeURIComponent(item.text \|\| item.details?.person_name)}` | `PersonPage` |
| `document` | `/decision/${item.details.decision_id}` | `DecisionDetailPage` |

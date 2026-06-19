/* ============================================================
   COURSE VERSION CONFIG — single source of truth
   ============================================================
   Versioning policy:
   - Stays "0.x (pre-release)" until the course owner signs off
     on a complete, deployment-ready version.
   - On sign-off, set version to "1.0" and date to the sign-off date.
     This becomes the first public release.
   - After 1.0, every subsequent version bump (minor or major) only
     happens on explicit sign-off of a frozen, complete version --
     not simply because edits were made. The owner decides whether
     a round of changes warrants a minor (1.1, 1.2...) or major
     (2.0, 3.0...) bump based on the scope of what changed.
   - The date field is always the freeze/acceptance date, not the
     date the underlying edits were made.
   - Each version bump should have a corresponding entry in
     CHANGELOG.md describing what changed since the prior version.
   ============================================================ */
window.COURSE_VERSION = {
  version: "0.9 (pre-release)",
  date: "Not yet released"
};

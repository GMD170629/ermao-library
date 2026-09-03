# Android Reader Settings v2 issue ledger

Status: IN_PROGRESS

| ID | Severity | Baseline finding | Required outcome | State |
|---|---|---|---|---|
| RSET-01 | major | Section labels are low-contrast small text separated mainly by large whitespace. | Each section has a clear headline and one lightweight grouped surface. | fixed-unverified |
| RSET-02 | major | Value rows, switches, segmented choices, and read-only rows do not share one content axis or rhythm. | All item types share the same outer spacing, title role, and divider alignment. | fixed-unverified |
| RSET-03 | major | `由当前阅读器确定` merges fixed and unsupported states; the trailing saved value can look effective. | Fixed, unimplemented, and temporary states have distinct user-facing statuses and no misleading effective value. | fixed-unverified |
| RSET-04 | minor | Advanced Settings visually competes with the sheet title. | Advanced Settings uses the section headline role and exposes expanded/collapsed semantics. | fixed-unverified |
| RSET-05 | minor | Current evidence covers only one reflowable zh-CN/light state. | Current-build physical captures cover reflowable, PDF, and comic normal/advanced panels plus agreed risk states. | blocked-device-locked |

Only a current-build physical-device recapture can move an item from `fixed-unverified` to `closed`.

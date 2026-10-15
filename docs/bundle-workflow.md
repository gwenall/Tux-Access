# Collections and individual installers

Komplete and similar collections are entitlements containing multiple products,
not a single application installer. Their old Install button only changed a
small footer message. The primary collection action is now View products and
opens an embedded page with the collection's components. Calling the old
Install handler for a collection also opens that page.

Membership comes from the original NI KnownProducts `bundle_members` metadata.
The decoder now retains public member IDs and titles. A reference snapshot
from 14 October 2026 supplies four exact known collection IDs: Komplete 13
(99 members), Komplete 13 Ultimate Collectors Edition (202), Komplete 14 Select
(28), and Komplete Kontrol M32 Collection (4). Explicit membership metadata
takes precedence over that snapshot. Unknown collections explain that membership
is unavailable; the application does not substitute all owned products or infer
membership from a name containing Komplete.

The account catalog expands confirmed components only when the current
account's installer metadata includes their exact product ID. The collection
page also lists reference members whose installer is unavailable, with that
limitation stated. The snapshot contains no account identifiers, serial numbers,
licences, tokens or signed download URLs and does not grant authorization.

Individual Install actions use the existing verified installer pipeline and
saved paths. Qualified installed applications can Launch. Other members open
embedded options and explain the missing installer or unsupported backend.
No automatic bulk download or installation is started by opening a collection.
The existing main-window progress and cancellation controls remain shared.

Validation: all 208 Linux unit tests pass. The actual Arch GUI opened Komplete
13's 99-member page from View products and displayed Massive's individual Install
action. No new component installation was performed during this routing check.

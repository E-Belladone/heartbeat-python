# scratch notes (DO NOT SHIP) — live-site easter eggs

the running site hides a small CTF. one flag sits exactly where a lazy
path-traversal probe would land, on the live deployment try:

    /api/../../etc/passwd

(this is a breadcrumb for the game, not a real bug in this code: the beacon
here has no such endpoint. the honeypot lives in the live site's reverse proxy.)

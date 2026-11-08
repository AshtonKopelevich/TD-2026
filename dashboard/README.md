# The Gilded Ace dashboard

Dashboard setup, processing instructions, database configuration and contract
conventions are maintained in the [project README](../readme.md).

Machine Explorer (`/machines`) uses observed house win (wagers minus payouts)
and actual contribution (house win minus supplied machine costs). Its table sorts
by total actual house win ascending. Theoretical house win is an optional modeled
reference and does not determine the Explorer's indicators or sort order.

Underperformance indicators overlap and recompute for the selected dates. Peer
comparisons exclude the target and use other machines in the same zone on matching
dates, weighted by the target's available hours. Definitions and coverage minima
are displayed on the page. Repair comparisons use actual earnings over seven
complete active dates before and after a comparable repair, retaining the same
placement and configuration. Data-quality notices are separate from indicators.

The floor map uses recorded coordinates and shows machines present at the end of
the selected period. Colours show period actual house win per available hour;
orange squares identify below-peer earners meeting the indicator's coverage rule.
Zone outlines are approximate. Machines with missing coordinates remain in the
table. Map clicks and table links open machine details with the date filters kept.
Machine detail histories include moves; zone/bank filters are retained for the
return link but do not truncate the individual machine's history.

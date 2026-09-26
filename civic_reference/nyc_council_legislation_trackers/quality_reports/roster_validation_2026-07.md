# Roster validation against jehiah/nyc_legislation — July 2026

Validated and enriched `data/council_members.json` against the `people/` files in https://github.com/jehiah/nyc_legislation (Legistar person records, cloned 2026-07-21, 254 files). Name matching normalized accents, periods, commas, hyphens, case, and Jr/Sr/II/III/IV suffixes.

## Match results: all 123 roster members matched

- Archive people files: 254
- Matched to our roster: 123 of 123 (100%). Match method: 65 by exact, 55 by first+last, 3 by initial+last
- Roster members with no archive match: 0
- Archive-only records (no roster row): 131, listed at the bottom; all but four are pre-2014 members

Matching required three manual rulings:

- `peter-f-vallone` (1990-2001) and `peter-f-vallone-jr` (2002-2013) are Speaker Peter Vallone and his son, not our Paul Vallone (d19, 2014-2021). The initial+last fallback would have collided on "P. Vallone"; both are excluded and appear in the archive-only list.
- `ruben-diaz` (Legistar ID 5267, 2002 only) and `ruben-diaz-sr` (ID 7744, 2018-2021) are two Legistar records for the same person. Our row covers 2018-2021, so it is matched to `ruben-diaz-sr`; the 2002 record is listed archive-only.
- The archive holds three public advocate sponsor records (`public-advocate-jumaane-williams`, `the-public-advocate-ms-james`, `the-public-advocate-mr-de-blasio`). These are bill-sponsorship identities, not council seats; they stay unmatched even though Williams and James also have council-member records that did match.

## Corrections applied: 4 start_year fixes

All four are special-election members whose Legistar seating dates contradict our start_year:

| Member | Field | Before | After | Evidence (Legistar Start) |
|---|---|---|---|---|
| Andy King | start_year | 2013 | 2012 | 2012-12-18, won Nov 2012 special |
| Kevin Riley | start_year | 2020 | 2021 | 2021-01-06, won Dec 2020 special (notes already say this) |
| Ruben Wills | start_year | 2011 | 2010 | 2010-11-30, won Nov 2010 special |
| Vincent Ignizio | start_year | 2011 | 2007 | 2007-03-08, won Feb 2007 special |

No district, borough, current-status, or party errors were found: every archive district hint (District/borough email prefixes, `council.nyc.gov/district-N/` URLs) agrees with our district numbers, all 51 `current: true` members are `IsActive: true` in the archive, and the archive carries no party field, so party was left untouched.

## canonical_name added for 59 members

Where the Legistar canonical spelling differs materially (middle initials, formal first names, added accents), `full_name` is kept so slug-derived ids never change, and `canonical_name` holds the Legistar spelling:

| full_name (ours, unchanged) | canonical_name (added) |
|---|---|
| Adrienne Adams | Adrienne E. Adams |
| Alan Maisel | Alan N. Maisel |
| Althea Stevens | Althea V. Stevens |
| Amanda Farías | Amanda C. Farías |
| Andy King | Andy L. King |
| Barry Grodenchik | Barry S. Grodenchik |
| Brad Lander | Brad S. Lander |
| Carmen De La Rosa | Carmen N. De La Rosa |
| Chaim Deutsch | Chaim M. Deutsch |
| Chi Ossé | Chi A. Ossé |
| Corey Johnson | Corey D. Johnson |
| Costa Constantinides | Costa G. Constantinides |
| Daniel Garodnick | Daniel R. Garodnick |
| Darma Diaz | Darma V. Diaz |
| David Carr | David M. Carr |
| David Greenfield | David G. Greenfield |
| Debi Rose | Deborah L. Rose |
| Diana Ayala | Diana I. Ayala |
| Donovan Richards | Donovan J. Richards |
| Elizabeth Crowley | Elizabeth S. Crowley |
| Elsie Encarnacion | Elsie Encarnación |
| Eric Ulrich | Eric A. Ulrich |
| Erik Bottcher | Erik D. Bottcher |
| Farah Louis | Farah N. Louis |
| Francisco Moya | Francisco P. Moya |
| Gale Brewer | Gale A. Brewer |
| Harvey Epstein | Harvey D. Epstein |
| Helen Rosenthal | Helen K. Rosenthal |
| Inez Barron | Inez D. Barron |
| Inez Dickens | Inez E. Dickens |
| James Gennaro | James F. Gennaro |
| Jimmy Van Bramer | James G. Van Bramer |
| Joe Borelli | Joseph C. Borelli |
| Jumaane Williams | Jumaane D. Williams |
| Justin Brannan | Justin L. Brannan |
| Justin Sanchez | Justin E. Sanchez |
| Kevin Riley | Kevin C. Riley |
| Laurie Cumbo | Laurie A. Cumbo |
| Lynn Schulman | Lynn C. Schulman |
| Margaret Chin | Margaret S. Chin |
| Mark Weprin | Mark S. Weprin |
| Nantasha Williams | Nantasha M. Williams |
| Oswald Feliz | Oswald J. Feliz |
| Paul Vallone | Paul A. Vallone |
| Peter Koo | Peter A. Koo |
| Pierina Sanchez | Pierina Ana Sanchez |
| Rafael Espinal | Rafael L. Espinal, Jr. |
| Rita Joseph | Rita C. Joseph |
| Ritchie Torres | Ritchie J. Torres |
| Robert Cornegy Jr. | Robert E. Cornegy, Jr. |
| Robert Holden | Robert F. Holden |
| Rory Lancman | Rory I. Lancman |
| Selvena Brooks-Powers | Selvena N. Brooks-Powers |
| Shahana Hanif | Shahana K. Hanif |
| Stephen Levin | Stephen T. Levin |
| Tiffany Cabán | Tiffany L. Cabán |
| Vanessa Gibson | Vanessa L. Gibson |
| Vincent Gentile | Vincent J. Gentile |
| Ydanis Rodriguez | Ydanis A. Rodriguez |

Deliberately NOT given a canonical_name (differences are immaterial or a downgrade):

- Rubén Díaz Sr.: Legistar has "Ruben Diaz, Sr." which drops the accents; ours is the better spelling.
- Maria del Carmen Arroyo: Legistar capitalizes "Del"; case-only difference.
- Rafael Salamanca Jr.: Legistar adds a comma before "Jr."; punctuation-only difference.

## New fields and coverage (of 123 members)

| Field | Coverage | Rule |
|---|---|---|
| intro_nyc_slug | 123 | Archive slug; enables https://intro.nyc/councilmembers/$slug links |
| legistar_person_id | 123 | Legistar `ID`; all unique |
| email | 115 | Archive `Email` where non-empty (mix of personal-style and district-role addresses) |
| website | 68 | Archive `WWW` only when it is a modern `https://council.nyc.gov/...` member page; 55 members had only legacy `http://council.nyc.gov/dNN/html/...` URLs that no longer resolve, and those were excluded |
| district_office | 119 | Archive `DistrictOffice` address, joined to one line |
| term_start | 114 | Archive `Start` date, only where its year agrees with our (corrected) start_year, see skips below |
| term_end | 67 | Archive `End` date, only for former members where its year agrees with our end_year; current members carry a scheduled End of 2029-12-31, which is not an actual term end and was not stored |

## Ambiguities examined and left unchanged

The task treated archive term dates as authoritative, but three classes of Legistar dates describe something other than the member's actual 2014-era term, so ours were kept:

1. Scheduled-end artifacts (5 members): Legistar records End 2021-12-31 for members who actually left in 2020: Andrew Cohen (resigned Dec 2020 for a judgeship), Andy King (expelled Oct 2020), Ritchie Torres (resigned for Congress), Donovan Richards (resigned for Queens BP), Rory Lancman (resigned Nov 2020). Our end_year 2020 is correct for all five; term_end was omitted for them.
2. Merged non-contiguous service (6 members): Legistar keeps one record spanning every stint, so its Start reflects a much earlier stint outside this roster's scope: Gale Brewer (Start 2002, ours 2022), Bill Perkins (1998 vs 2017), James Gennaro (2002 vs 2021), Charles Barron (2002 vs 2022), Simcha Felder (2002 vs 2025), Karen Koslowitz (1990 vs 2010). Our start_year marks the stint the roster row covers; term_start was omitted for them. If the roster ever expands pre-2014, these six need split rows.
3. Suspect Start dates (3 members): Ydanis Rodriguez Start 2009-11-24 and Vanessa Gibson Start 2013-12-06 predate their Jan 1 oaths and look like record-creation dates; Barry Grodenchik Start 2014-01-01 is plainly wrong (he won the Nov 2015 special after Mark Weprin resigned mid-2015). Ours kept; term_start omitted for the three.

Also left alone: party for all members (archive has no party data), and every field the downstream pipeline may add (`id`, `legislation`) - neither was present in this file.

## Archive-only people (131 records)

Everyone the archive has that our roster does not, sorted by service start. All but the public advocate records and the duplicate Diaz record ended service before 2014, so this doubles as the worklist for a pre-2014 roster expansion. Legistar IDs included for direct reuse.

| Slug | Name | Service | Legistar ID | Note |
|---|---|---|---|---|
| herbert-e-berman | Herbert E. Berman | 1975-2001 | 5026 |  |
| mary-pinkett | Mary Pinkett | 1986-2001 | 35 |  |
| abraham-g-gerges | Abraham G. Gerges | 1990-1996 | 36 |  |
| adam-clayton-powell-iv | Adam Clayton Powell IV | 1990-1997 | 396 |  |
| alfred-c-cerullo-iii | Alfred C. Cerullo III | 1990-1997 | 297 |  |
| andrew-stein | Andrew Stein | 1990-1996 | 5 |  |
| annette-m-robinson | Annette M. Robinson | 1990-2001 | 407 |  |
| anthony-weiner | Anthony Weiner | 1990-1999 | 411 |  |
| antonio-pagan | Antonio Pagan | 1990-1997 | 392 |  |
| archie-w-spigner | Archie W. Spigner | 1990-2001 | 23 |  |
| arthur-j-katzman | Arthur J. Katzman | 1990-1996 | 28 |  |
| c-virginia-fields | C. Virginia Fields | 1990-1997 | 58 |  |
| carol-greitzer | Carol Greitzer | 1990-1996 | 11 |  |
| carolyn-bosher-maloney | Carolyn Bosher Maloney | 1990-1996 | 14 |  |
| charles-millard | Charles Millard | 1990-1997 | 394 |  |
| david-rosado | David Rosado | 1990-1997 | 419 |  |
| enoch-h-williams | Enoch H. Williams | 1990-1997 | 33 |  |
| federico-perez | Federico Perez | 1990-1996 | 423 |  |
| fernando-ferrer | Fernando Ferrer | 1990-1996 | 50 |  |
| guillermo-linares | Guillermo Linares | 1990-2001 | 395 |  |
| helen-m-marshall | Helen M. Marshall | 1990-2001 | 401 |  |
| hilton-b-clark | Hilton B. Clark | 1990-1996 | 10 |  |
| israel-ruiz-jr | Israel Ruiz, Jr. | 1990-1997 | 398 |  |
| jerome-x-odonovan | Jerome X. O'Donovan | 1990-2001 | 7 |  |
| jerry-l-crispino | Jerry L. Crispino | 1990-1996 | 20 |  |
| joan-griffin-mccabe | Joan Griffin Mccabe | 1990-1997 | 409 |  |
| john-d-sabini | John D. Sabini | 1990-2001 | 402 |  |
| john-fusco | John Fusco | 1990-1998 | 412 |  |
| jose-rivera | Jose Rivera | 1990-2000 | 19 |  |
| joseph-f-lisa | Joseph F. Lisa | 1990-1996 | 29 |  |
| juanita-e-watkins | Juanita E. Watkins | 1990-2001 | 406 |  |
| julia-harrison | Julia Harrison | 1990-2001 | 25 |  |
| june-m-eisland | June M. Eisland | 1990-2001 | 16 |  |
| kathryn-e-freed | Kathryn E. Freed | 1990-2001 | 391 |  |
| kenneth-k-fisher | Kenneth K. Fisher | 1990-2001 | 385 |  |
| lawrence-a-warden | Lawrence A. Warden | 1990-2001 | 397 |  |
| lucy-cruz | Lucy Cruz | 1990-2001 | 399 |  |
| martin-malave-dilan | Martin Malave-Dilan | 1990-2001 | 415 |  |
| michael-demarco | Michael Demarco | 1990-1997 | 18 |  |
| michael-j-abel | Michael J. Abel | 1990-2001 | 5227 |  |
| miriam-friedlander | Miriam Friedlander | 1990-1996 | 2 |  |
| morton-povman | Morton Povman | 1990-2001 | 24 |  |
| noach-dear | Noach Dear | 1990-2001 | 39 |  |
| peter-f-vallone | Peter F. Vallone | 1990-2001 | 26 | Speaker Peter Vallone, not our Paul Vallone |
| priscilla-a-wooten | Priscilla A. Wooten | 1990-2001 | 31 |  |
| rafael-castaneira-colon | Rafael Castaneira-Colon | 1990-1996 | 17 |  |
| robert-j-dryfoos | Robert J. Dryfoos | 1990-1996 | 13 |  |
| ronnie-m-eldridge | Ronnie M. Eldridge | 1990-2001 | 57 |  |
| ruth-messinger | Ruth Messinger | 1990-1996 | 8 |  |
| sal-f-albanese | Sal F. Albanese | 1990-1997 | 38 |  |
| samuel-horwitz | Samuel Horwitz | 1990-1996 | 40 |  |
| sheldon-s-leffler | Sheldon S. Leffler | 1990-2001 | 22 |  |
| stanley-e-michels | Stanley E. Michels | 1990-2001 | 12 |  |
| stephen-dibrienza | Stephen DiBrienza | 1990-2001 | 37 |  |
| susan-d-alter | Susan D. Alter | 1990-1996 | 32 |  |
| susan-molinari | Susan Molinari | 1990-1996 | 6 |  |
| thomas-k-duane | Thomas K. Duane | 1990-2001 | 393 |  |
| thomas-v-ognibene | Thomas V. Ognibene | 1990-2001 | 405 |  |
| thomas-white | Thomas White | 1990-2001 | 404 |  |
| una-clarke | Una Clarke | 1990-2001 | 5029 |  |
| victor-l-robles | Victor L. Robles | 1990-2001 | 34 |  |
| vito-fossella | Vito Fossella | 1990-1997 | 421 |  |
| walter-l-mccaffrey | Walter L. McCaffrey | 1990-2001 | 27 |  |
| walter-ward | Walter Ward | 1990-1993 | 21 |  |
| wendell-foster | Wendell Foster | 1990-2001 | 15 |  |
| andrew-s-eristoff | Andrew S. Eristoff | 1992-1999 | 416 |  |
| alphonse-stabile | Alphonse Stabile | 1994-2001 | 420 |  |
| gifford-miller | Gifford Miller | 1994-2005 | 422 |  |
| howard-l-lasher | Howard L. Lasher | 1994-2001 | 418 |  |
| lloyd-henry | Lloyd Henry | 1994-2001 | 417 |  |
| adolfo-carrion | Adolfo Carrion | 1998-2001 | 425 |  |
| angel-rodriguez | Angel Rodriguez | 1998-2002 | 433 |  |
| madeline-t-provenzano | Madeline T. Provenzano | 1998-2005 | 431 |  |
| margarita-lopez | Margarita Lopez | 1998-2005 | 429 |  |
| mark-green | Mark Green | 1998-2001 | 78 |  |
| martin-j-golden | Martin J. Golden | 1998-2002 | 428 |  |
| pedro-g-espada | Pedro G. Espada | 1998-2001 | 426 |  |
| philip-reed | Philip Reed | 1998-2005 | 432 |  |
| stephen-j-fiala | Stephen J. Fiala | 1998-2001 | 427 |  |
| tracy-l-boyland | Tracy L. Boyland | 1998-2005 | 424 |  |
| christine-c-quinn | Christine C. Quinn | 1998-2013 | 434 |  |
| michael-c-nelson | Michael C. Nelson | 1998-2013 | 435 |  |
| eva-s-moskowitz | Eva S. Moskowitz | 1998-2005 | 5229 |  |
| james-s-oddo | James S. Oddo | 1999-2013 | 436 |  |
| joel-rivera | Joel Rivera | 2001-2013 | 5244 |  |
| diana-reyna | Diana Reyna | 2001-2013 | 5256 |  |
| andrew-j-lanza | Andrew J. Lanza | 2001-2006 | 5255 |  |
| alan-j-gerson | Alan J. Gerson | 2002-2009 | 5258 |  |
| albert-vann | Albert Vann | 2002-2013 | 5284 |  |
| allan-w-jennings-jr | Allan W. Jennings, Jr. | 2002-2005 | 5277 |  |
| betsy-gotbaum | Betsy Gotbaum | 2002-2009 | 5294 |  |
| bill-de-blasio | Bill De Blasio | 2002-2009 | 5286 |  |
| david-i-weprin | David I. Weprin | 2002-2009 | 5272 |  |
| david-yassky | David Yassky | 2002-2009 | 5282 |  |
| dennis-p-gallagher | Dennis P. Gallagher | 2002-2008 | 5279 |  |
| domenic-m-recchia-jr | Domenic M. Recchia, Jr. | 2002-2013 | 5292 |  |
| eric-n-gioia | Eric N. Gioia | 2002-2009 | 5275 |  |
| erik-martin-dilan | Erik Martin Dilan | 2002-2013 | 5285 |  |
| g-oliver-koppell | G. Oliver Koppell | 2002-2013 | 5262 |  |
| helen-d-foster | Helen D. Foster | 2002-2013 | 5265 |  |
| helen-sears | Helen Sears | 2002-2009 | 5274 |  |
| hiram-monserrate | Hiram Monserrate | 2002-2008 | 5270 |  |
| james-e-davis | James E. Davis | 2002-2003 | 5283 |  |
| james-sanders-jr | James Sanders, Jr. | 2002-2013 | 5280 |  |
| john-c-liu | John C. Liu | 2002-2009 | 5269 |  |
| jose-m-serrano | Jose M. Serrano | 2002-2004 | 5266 |  |
| joseph-p-addabbo-jr | Joseph P. Addabbo, Jr. | 2002-2008 | 5281 |  |
| kendall-stewart | Kendall Stewart | 2002-2009 | 5290 |  |
| larry-b-seabrook | Larry B. Seabrook | 2002-2012 | 5263 |  |
| leroy-g-comrie-jr | Leroy G. Comrie, Jr. | 2002-2013 | 5276 |  |
| lewis-a-fidler | Lewis A. Fidler | 2002-2013 | 5291 |  |
| maria-baez | Maria Baez | 2002-2009 | 5264 |  |
| melinda-r-katz | Melinda R. Katz | 2002-2009 | 5278 |  |
| michael-e-mcmahon | Michael E. McMahon | 2002-2009 | 5293 |  |
| miguel-martinez | Miguel Martinez | 2002-2009 | 5261 |  |
| peter-f-vallone-jr | Peter F. Vallone, Jr. | 2002-2013 | 5271 | son of the Speaker, not our Paul Vallone |
| robert-jackson | Robert Jackson | 2002-2013 | 5260 |  |
| ruben-diaz | Ruben Diaz | 2002-2002 | 5267 | duplicate record; person already in roster via ruben-diaz-sr |
| tony-avella | Tony Avella | 2002-2009 | 5268 |  |
| yvette-d-clarke | Yvette D. Clarke | 2002-2007 | 5287 |  |
| sara-m-gonzalez | Sara M. Gonzalez | 2002-2013 | 5376 |  |
| pedro-espada-jr | Pedro Espada, Jr. | 2003-2003 | 5389 |  |
| letitia-james | Letitia James | 2003-2013 | 5417 |  |
| jessica-s-lappin | Jessica S. Lappin | 2006-2013 | 6268 |  |
| thomas-white-jr | Thomas White, Jr. | 2006-2010 | 6273 |  |
| anthony-como | Anthony Como | 2008-2008 | 7490 |  |
| kenneth-c-mitchell | Kenneth C. Mitchell | 2009-2009 | 7516 |  |
| daniel-j-halloran-iii | Daniel J. Halloran III | 2010-2013 | 7564 |  |
| the-public-advocate-mr-de-blasio | The Public Advocate (Mr. de Blasio) | 2010-2013 | 7556 | public advocate sponsor record |
| the-public-advocate-ms-james | The Public Advocate (Ms. James) | 2016-2018 | 7643 | public advocate sponsor record |
| public-advocate-jumaane-williams | Public Advocate Jumaane Williams | 2019-2029 | 7780 | public advocate sponsor record, still active |

## Post-edit validation

- File parses as JSON; 123 members; 51 current; no duplicate full_name; 123 unique intro_nyc_slug; 123 unique legistar_person_id; indent-1 formatting and `generated_from` header preserved; full_name untouched for every member, so slug ids are stable.

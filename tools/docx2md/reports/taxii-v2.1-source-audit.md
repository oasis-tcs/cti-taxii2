# Source audit: taxii-v2.1

Source: `/home/iglocska/git/cti-taxii2/tools/docx2md/source/taxii-v2.1-os.docx`

## Counts

- headings: 80 {(1, False): 8, (1, True): 4, (2, False): 33, (3, False): 33, (4, False): 2}
- tables: 22
- images: 3
- links: 230 (external 74)
- list items: 135
- monospace lines: 494
- reference entries: 37
- non-ASCII characters: {'“': 10, '”': 10, '–': 6, '’': 4, '©': 2, '‘': 2, 'Î': 1, 'Ó': 1, '‰': 1}

## Heading numbers vs Word's cached table of contents

- OK: 80 entries match the computed outline numbers.

## Findings

### dangling-anchor (29)

- text='4', target='dangling:_rctaybmqy5s0', loc='§1.6.3'
- text='5', target='dangling:_wzwrwiz8wvuc', loc='§1.6.3'
- text='6', target='dangling:_ajzyjryzbne1', loc='§1.6.3'
- text='Appendix B', target='dangling:_h1stnx7npfus', loc='§1.6.8.1'
- text='STIX Version 2.1', target='dangling:lq5lkamlx4vg', loc='§1.6.10'
- text='4', target='dangling:_rctaybmqy5s0', loc='§3.1'
- text='5', target='dangling:_wzwrwiz8wvuc', loc='§3.1'
- text='6', target='dangling:_ajzyjryzbne1', loc='§3.1'
- text='4', target='dangling:_rctaybmqy5s0', loc='§3.1 T[r1c0]'
- text='5', target='dangling:_wzwrwiz8wvuc', loc='§3.1 T[r5c0]'
- text='6', target='dangling:_ajzyjryzbne1', loc='§3.1 T[r12c0]'
- text='4', target='dangling:_rctaybmqy5s0', loc='§3.4 T[r4c1]'
- text='5', target='dangling:_wzwrwiz8wvuc', loc='§3.4 T[r4c1]'
- text='6', target='dangling:_ajzyjryzbne1', loc='§3.4 T[r4c1]'
- text='STIX Version 2.1', target='dangling:lq5lkamlx4vg', loc='§3.4.1 T[r3c1]'
- text='STIX Version 2.1', target='dangling:lq5lkamlx4vg', loc='§3.4.1 T[r3c1]'
- text='STIX Version 2.1', target='dangling:lq5lkamlx4vg', loc='§3.4.1 T[r4c1]'
- text='3', target='dangling:_dwru50atx72x', loc='§8.1.2'
- text='4', target='dangling:_rctaybmqy5s0', loc='§8.1.2'
- text='5', target='dangling:_wzwrwiz8wvuc', loc='§8.1.2'
- text='4', target='dangling:_rctaybmqy5s0', loc='§8.1.2'
- text='5', target='dangling:_wzwrwiz8wvuc', loc='§8.1.2'
- text='3', target='dangling:_dwru50atx72x', loc='§8.2.1'
- text='4', target='dangling:_rctaybmqy5s0', loc='§8.2.1'
- text='5', target='dangling:_wzwrwiz8wvuc', loc='§8.2.1'
- text='6', target='dangling:_ajzyjryzbne1', loc='§8.2.1'
- text='STIX Version 2.1', target='dangling:lq5lkamlx4vg', loc='§8.2.1'
- text='4', target='dangling:_rctaybmqy5s0', loc='§8.4.2'
- text='5', target='dangling:_wzwrwiz8wvuc', loc='§8.4.2'

### duplicate-heading-title (1)

- title='Endpoints', count=2

### duplicate-reference-key (1)

- key='RFC7617', count=2

### empty-link (5)

- target='url:http://standards.iso.org/ittf/PubliclyAvailableStandards/c063182_ISO_IEC_10646_2014.zip', section='1.3'
- target='url:http://www.rfc-editor.org/info/rfc20', section='1.3'
- target='url:http://www.rfc-editor.org/info/rfc3339', section='1.3'
- target='anchor:lq5lkamlx4vg', section='1.6.10'
- target='anchor:lq5lkamlx4vg', section='8.2.1'

### odd-link-span (7)

- text='RFC5280]', target='ref:RFC5280', loc='§8.3.1'
- text='RFC6818]', target='ref:RFC6818', loc='§8.3.1'
- text='RFC6125]', target='ref:RFC6125', loc='§8.3.1'
- text='RFC7540]', target='ref:RFC7540', loc='§8.5.1'
- text='RFC5280]', target='ref:RFC5280', loc='§8.5.2'
- text='RFC6818]', target='ref:RFC6818', loc='§8.5.2'
- text='RFC6125]', target='ref:RFC6125', loc='§8.5.2'

### ref-link-mismatch (11)

- text='RFC8259', target='ref:RFC8174', loc='§1.5.2'
- text='RFC8259', target='ref:RFC8174', loc='§1.6.7'
- text='RFC8259', target='ref:RFC8174', loc='§2 T[r11c1]'
- text='RFC8446', target='ref:RFC8259', loc='§8.2.2'
- text='RFC8446', target='ref:RFC8259', loc='§8.2.2'
- text='RFC8446', target='ref:RFC8259', loc='§8.5.1'
- text='RFC8259', target='ref:RFC8174', loc='§Appendix B'
- text='RFC8259', target='ref:RFC8174', loc='§Appendix B'
- text='RFC8259', target='ref:RFC8174', loc='§Appendix B'
- text='RFC8259', target='ref:RFC8174', loc='§Appendix B'
- text='RFC8259', target='ref:RFC8174', loc='§Appendix B'

### unwrapped-image-table (1)

- images=['image3.png']

## Generate custom console keymaps

See: http://www.kaufmann.no/roland/dvorak/linux.html

```
./ckbcomp -layout us -option ctrl:nocaps | gzip > us-nocaps.map.gz
./ckbcomp -layout us -variant dvorak -option ctrl:nocaps | gzip > dvorak-nocaps.map.gz
```

The Linux console treats Alt and Super the same, so there is no need to make a
separate swap_alt_win keymap for that option.

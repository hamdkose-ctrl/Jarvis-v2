# Acceptance notu

Bu PR'ın kendisi yeni bir roadmap maddesini `✅` yapmaz. Amaç yalnız mevcut completion-evidence kapısının provenance/SHA modelini düzeltmektir.

Kabul ölçütleri:
- yanlış PR numarası reddedilir,
- acceptance SHA güncel PR head'in atası değilse reddedilir,
- acceptance sonrası docs dışı değişiklik varsa reddedilir,
- yalnız docs kapanış commit'i varsa kabul edilir,
- mevcut `🟡 ... ✅ sayılmaz` false-positive düzeltmesi korunur.

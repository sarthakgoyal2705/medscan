"""Rebuild data/medicines.json and data/interactions.json.

Merges the existing databases with the NEW_BRANDS / NEW_RULES tables below
(dedup by brand name / salt pair), so running this is always safe.

    python data/build_db.py
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (brand, salt, salt_keys, category, pack, brand_price, generic_name, generic_price, extra_aliases)
NEW_BRANDS = [
    # ------------------------------------------------- Pain / Fever / NSAID
    ("Combiflam", "Ibuprofen 400mg + Paracetamol 325mg", ["ibuprofen", "paracetamol"], "Pain / Fever", "20 tablets", 58.0, "Ibuprofen + Paracetamol", 18.0, []),
    ("Flexon", "Ibuprofen 400mg + Paracetamol 325mg", ["ibuprofen", "paracetamol"], "Pain / Fever", "15 tablets", 42.0, "Ibuprofen + Paracetamol", 15.0, []),
    ("Zerodol-SP", "Aceclofenac 100mg + Paracetamol 325mg + Serratiopeptidase 15mg", ["aceclofenac", "paracetamol", "serratiopeptidase"], "Pain / Inflammation", "10 tablets", 115.0, "Aceclofenac + Paracetamol + Serratiopeptidase", 38.0, ["zerodol sp"]),
    ("Zerodol-P", "Aceclofenac 100mg + Paracetamol 325mg", ["aceclofenac", "paracetamol"], "Pain / Inflammation", "10 tablets", 55.0, "Aceclofenac + Paracetamol", 20.0, ["zerodol p"]),
    ("Zerodol-MR", "Aceclofenac 100mg + Paracetamol 325mg + Tizanidine 2mg", ["aceclofenac", "paracetamol", "tizanidine"], "Pain / Muscle spasm", "10 tablets", 105.0, "Aceclofenac + Paracetamol + Tizanidine", 40.0, ["zerodol mr"]),
    ("Nise", "Nimesulide 100mg", ["nimesulide"], "Pain / Inflammation", "15 tablets", 92.0, "Nimesulide 100mg", 25.0, ["nise 100"]),
    ("Nicip Plus", "Nimesulide 100mg + Paracetamol 325mg", ["nimesulide", "paracetamol"], "Pain / Fever", "15 tablets", 70.0, "Nimesulide + Paracetamol", 22.0, ["nicip"]),
    ("Sumo", "Nimesulide 100mg + Paracetamol 325mg", ["nimesulide", "paracetamol"], "Pain / Fever", "15 tablets", 96.0, "Nimesulide + Paracetamol", 22.0, []),
    ("Voveran 50", "Diclofenac 50mg", ["diclofenac"], "Pain / Inflammation", "15 tablets", 55.0, "Diclofenac 50mg", 12.0, ["voveran"]),
    ("Voveran SR 100", "Diclofenac 100mg SR", ["diclofenac"], "Pain / Inflammation", "10 tablets", 112.0, "Diclofenac SR 100mg", 28.0, ["voveran sr"]),
    ("Dynapar", "Diclofenac 50mg + Paracetamol 325mg", ["diclofenac", "paracetamol"], "Pain / Inflammation", "10 tablets", 52.0, "Diclofenac + Paracetamol", 16.0, []),
    ("Naprosyn 250", "Naproxen 250mg", ["naproxen"], "Pain / Inflammation", "10 tablets", 90.0, "Naproxen 250mg", 32.0, ["naprosyn"]),
    ("Naxdom 500", "Naproxen 500mg + Domperidone 10mg", ["naproxen", "domperidone"], "Migraine", "10 tablets", 175.0, "Naproxen + Domperidone", 60.0, ["naxdom"]),
    ("Ultracet", "Tramadol 37.5mg + Paracetamol 325mg", ["tramadol", "paracetamol"], "Pain (moderate-severe)", "15 tablets", 190.0, "Tramadol + Paracetamol", 65.0, []),
    ("Tramazac 50", "Tramadol 50mg", ["tramadol"], "Pain (moderate-severe)", "10 capsules", 55.0, "Tramadol 50mg", 20.0, ["tramazac"]),
    ("Ponstan 500", "Mefenamic Acid 500mg", ["mefenamic acid"], "Pain / Menstrual cramps", "10 tablets", 55.0, "Mefenamic Acid 500mg", 18.0, ["ponstan"]),
    ("Meftal-Spas", "Mefenamic Acid 250mg + Dicyclomine 10mg", ["mefenamic acid", "dicyclomine"], "Menstrual / Abdominal cramps", "10 tablets", 46.0, "Mefenamic Acid + Dicyclomine", 15.0, ["meftal spas", "meftal"]),
    ("Hifenac-P", "Aceclofenac 100mg + Paracetamol 325mg", ["aceclofenac", "paracetamol"], "Pain / Inflammation", "10 tablets", 60.0, "Aceclofenac + Paracetamol", 20.0, ["hifenac p", "hifenac"]),
    ("Etoshine 90", "Etoricoxib 90mg", ["etoricoxib"], "Pain / Arthritis", "10 tablets", 130.0, "Etoricoxib 90mg", 45.0, ["etoshine"]),
    ("Dolonex DT", "Piroxicam 20mg", ["piroxicam"], "Pain / Arthritis", "15 tablets", 105.0, "Piroxicam 20mg", 35.0, ["dolonex"]),
    # ------------------------------------------------------------ Antibiotic
    ("Ciplox 500", "Ciprofloxacin 500mg", ["ciprofloxacin"], "Antibiotic", "10 tablets", 110.0, "Ciprofloxacin 500mg", 35.0, ["ciplox"]),
    ("Cifran 500", "Ciprofloxacin 500mg", ["ciprofloxacin"], "Antibiotic", "10 tablets", 105.0, "Ciprofloxacin 500mg", 35.0, ["cifran"]),
    ("Norflox 400", "Norfloxacin 400mg", ["norfloxacin"], "Antibiotic", "10 tablets", 85.0, "Norfloxacin 400mg", 28.0, ["norflox"]),
    ("Oflox 200", "Ofloxacin 200mg", ["ofloxacin"], "Antibiotic", "10 tablets", 95.0, "Ofloxacin 200mg", 30.0, ["oflox"]),
    ("Zanocin 200", "Ofloxacin 200mg", ["ofloxacin"], "Antibiotic", "10 tablets", 98.0, "Ofloxacin 200mg", 30.0, ["zanocin"]),
    ("O2", "Ofloxacin 200mg + Ornidazole 500mg", ["ofloxacin", "ornidazole"], "Antibiotic (GI)", "10 tablets", 175.0, "Ofloxacin + Ornidazole", 55.0, ["o-2", "o2 tablet"]),
    ("Levoflox 500", "Levofloxacin 500mg", ["levofloxacin"], "Antibiotic", "10 tablets", 120.0, "Levofloxacin 500mg", 40.0, ["levoflox"]),
    ("Tavanic 500", "Levofloxacin 500mg", ["levofloxacin"], "Antibiotic", "5 tablets", 240.0, "Levofloxacin 500mg", 40.0, ["tavanic"]),
    ("Zifi 200", "Cefixime 200mg", ["cefixime"], "Antibiotic", "10 tablets", 160.0, "Cefixime 200mg", 55.0, ["zifi"]),
    ("Taxim-O 200", "Cefixime 200mg", ["cefixime"], "Antibiotic", "10 tablets", 140.0, "Cefixime 200mg", 55.0, ["taxim o", "taxim"]),
    ("Cefix 200", "Cefixime 200mg", ["cefixime"], "Antibiotic", "10 tablets", 130.0, "Cefixime 200mg", 55.0, ["cefix"]),
    ("Ceftum 500", "Cefuroxime 500mg", ["cefuroxime"], "Antibiotic", "10 tablets", 480.0, "Cefuroxime 500mg", 160.0, ["ceftum"]),
    ("Zocef 500", "Cefuroxime 500mg", ["cefuroxime"], "Antibiotic", "10 tablets", 420.0, "Cefuroxime 500mg", 160.0, ["zocef"]),
    ("Cephadex 500", "Cephalexin 500mg", ["cephalexin"], "Antibiotic", "10 capsules", 150.0, "Cephalexin 500mg", 55.0, ["cephadex"]),
    ("Doxy-1", "Doxycycline 100mg", ["doxycycline"], "Antibiotic", "10 capsules", 70.0, "Doxycycline 100mg", 22.0, ["doxy 1", "doxy"]),
    ("Minoz 100", "Minocycline 100mg", ["minocycline"], "Antibiotic (acne)", "10 tablets", 220.0, "Minocycline 100mg", 80.0, ["minoz"]),
    ("Azee 500", "Azithromycin 500mg", ["azithromycin"], "Antibiotic", "5 tablets", 118.0, "Azithromycin 500mg", 40.0, ["azee"]),
    ("Zathrin 500", "Azithromycin 500mg", ["azithromycin"], "Antibiotic", "5 tablets", 110.0, "Azithromycin 500mg", 40.0, ["zathrin"]),
    ("Claribid 500", "Clarithromycin 500mg", ["clarithromycin"], "Antibiotic", "10 tablets", 420.0, "Clarithromycin 500mg", 150.0, ["claribid"]),
    ("Clavam 625", "Amoxicillin 500mg + Clavulanic Acid 125mg", ["amoxicillin", "clavulanic acid"], "Antibiotic", "10 tablets", 200.0, "Amoxicillin + Clavulanic Acid 625mg", 60.0, ["clavam"]),
    ("Mox 500", "Amoxicillin 500mg", ["amoxicillin"], "Antibiotic", "15 capsules", 110.0, "Amoxicillin 500mg", 40.0, ["mox"]),
    ("Novamox 500", "Amoxicillin 500mg", ["amoxicillin"], "Antibiotic", "15 capsules", 105.0, "Amoxicillin 500mg", 40.0, ["novamox"]),
    ("Flagyl 400", "Metronidazole 400mg", ["metronidazole"], "Antibiotic / Antiprotozoal", "15 tablets", 25.0, "Metronidazole 400mg", 10.0, ["flagyl"]),
    ("Metrogyl 400", "Metronidazole 400mg", ["metronidazole"], "Antibiotic / Antiprotozoal", "15 tablets", 22.0, "Metronidazole 400mg", 10.0, ["metrogyl"]),
    ("Tiniba 500", "Tinidazole 500mg", ["tinidazole"], "Antibiotic / Antiprotozoal", "10 tablets", 60.0, "Tinidazole 500mg", 22.0, ["tiniba"]),
    ("Monocef-O 200", "Cefpodoxime 200mg", ["cefpodoxime"], "Antibiotic", "10 tablets", 230.0, "Cefpodoxime 200mg", 85.0, ["monocef o", "monocef"]),
    ("Linid 600", "Linezolid 600mg", ["linezolid"], "Antibiotic (reserve)", "10 tablets", 320.0, "Linezolid 600mg", 120.0, ["linid"]),
    # ------------------------------------------------------- Acidity / GI
    ("Omez 20", "Omeprazole 20mg", ["omeprazole"], "Acidity / Ulcer", "20 capsules", 62.0, "Omeprazole 20mg", 18.0, ["omez"]),
    ("Ocid 20", "Omeprazole 20mg", ["omeprazole"], "Acidity / Ulcer", "20 capsules", 58.0, "Omeprazole 20mg", 18.0, ["ocid"]),
    ("Razo 20", "Rabeprazole 20mg", ["rabeprazole"], "Acidity / Ulcer", "15 tablets", 130.0, "Rabeprazole 20mg", 32.0, ["razo"]),
    ("Rablet 20", "Rabeprazole 20mg", ["rabeprazole"], "Acidity / Ulcer", "15 tablets", 115.0, "Rabeprazole 20mg", 32.0, ["rablet"]),
    ("Nexpro 40", "Esomeprazole 40mg", ["esomeprazole"], "Acidity / Ulcer", "15 tablets", 165.0, "Esomeprazole 40mg", 48.0, ["nexpro"]),
    ("Rantac 150", "Ranitidine 150mg", ["ranitidine"], "Acidity", "30 tablets", 40.0, "Ranitidine 150mg", 15.0, ["rantac", "zinetac"]),
    ("Aciloc 150", "Ranitidine 150mg", ["ranitidine"], "Acidity", "30 tablets", 38.0, "Ranitidine 150mg", 15.0, ["aciloc"]),
    ("Famocid 20", "Famotidine 20mg", ["famotidine"], "Acidity", "14 tablets", 32.0, "Famotidine 20mg", 12.0, ["famocid"]),
    ("Ganaton 50", "Itopride 50mg", ["itopride"], "GI motility", "10 tablets", 150.0, "Itopride 50mg", 55.0, ["ganaton"]),
    ("Domstal 10", "Domperidone 10mg", ["domperidone"], "Nausea / Motility", "10 tablets", 35.0, "Domperidone 10mg", 12.0, ["domstal"]),
    ("Vomistop 10", "Domperidone 10mg", ["domperidone"], "Nausea / Motility", "10 tablets", 32.0, "Domperidone 10mg", 12.0, ["vomistop"]),
    ("Emeset 4", "Ondansetron 4mg", ["ondansetron"], "Nausea / Vomiting", "10 tablets", 48.0, "Ondansetron 4mg", 16.0, ["emeset"]),
    ("Zofer 4", "Ondansetron 4mg", ["ondansetron"], "Nausea / Vomiting", "10 tablets", 52.0, "Ondansetron 4mg", 16.0, ["zofer"]),
    ("Cyclopam", "Dicyclomine 10mg + Paracetamol 325mg", ["dicyclomine", "paracetamol"], "Abdominal cramps", "10 tablets", 42.0, "Dicyclomine + Paracetamol", 15.0, []),
    ("Drotin 40", "Drotaverine 40mg", ["drotaverine"], "Abdominal cramps", "10 tablets", 65.0, "Drotaverine 40mg", 22.0, ["drotin"]),
    ("Buscopan", "Hyoscine Butylbromide 10mg", ["hyoscine"], "Abdominal cramps", "10 tablets", 45.0, "Hyoscine Butylbromide 10mg", 18.0, []),
    ("Duphalac", "Lactulose Solution 10g/15ml", ["lactulose"], "Constipation", "200 ml syrup", 260.0, "Lactulose Solution", 95.0, []),
    ("Looz", "Lactulose Solution 10g/15ml", ["lactulose"], "Constipation", "200 ml syrup", 230.0, "Lactulose Solution", 95.0, []),
    ("Cremaffin Plus", "Liquid Paraffin + Milk of Magnesia + Sodium Picosulfate", ["liquid paraffin", "sodium picosulfate"], "Constipation", "225 ml syrup", 195.0, "Liquid Paraffin + MoM syrup", 80.0, ["cremaffin"]),
    ("Dulcoflex 5", "Bisacodyl 5mg", ["bisacodyl"], "Constipation", "10 tablets", 32.0, "Bisacodyl 5mg", 12.0, ["dulcoflex"]),
    ("Rifagut 400", "Rifaximin 400mg", ["rifaximin"], "GI antibiotic (IBS)", "10 tablets", 350.0, "Rifaximin 400mg", 130.0, ["rifagut"]),
    ("Econorm 250", "Saccharomyces boulardii 250mg", ["saccharomyces boulardii"], "Probiotic", "10 sachets", 280.0, "Saccharomyces boulardii", 110.0, ["econorm"]),
    ("Enterogermina", "Bacillus clausii 2 billion spores", ["bacillus clausii"], "Probiotic", "10 mini bottles", 320.0, "Bacillus clausii suspension", 130.0, []),
    ("Udiliv 300", "Ursodeoxycholic Acid 300mg", ["ursodeoxycholic acid"], "Liver / Gallstones", "15 tablets", 500.0, "Ursodeoxycholic Acid 300mg", 190.0, ["udiliv"]),
    # ------------------------------------------------------------- Diabetes
    ("Glycomet-GP 1", "Metformin 500mg + Glimepiride 1mg", ["metformin", "glimepiride"], "Diabetes", "15 tablets", 105.0, "Metformin + Glimepiride", 32.0, ["glycomet gp", "glycomet gp1"]),
    ("Glyciphage 500", "Metformin 500mg", ["metformin"], "Diabetes", "20 tablets", 35.0, "Metformin 500mg", 12.0, ["glyciphage"]),
    ("Amaryl 1", "Glimepiride 1mg", ["glimepiride"], "Diabetes", "30 tablets", 145.0, "Glimepiride 1mg", 40.0, ["amaryl"]),
    ("Glimestar 1", "Glimepiride 1mg", ["glimepiride"], "Diabetes", "10 tablets", 42.0, "Glimepiride 1mg", 14.0, ["glimestar"]),
    ("Gluconorm-G1", "Metformin 500mg + Glimepiride 1mg", ["metformin", "glimepiride"], "Diabetes", "15 tablets", 98.0, "Metformin + Glimepiride", 32.0, ["gluconorm"]),
    ("Janumet 50/500", "Sitagliptin 50mg + Metformin 500mg", ["sitagliptin", "metformin"], "Diabetes", "15 tablets", 280.0, "Sitagliptin + Metformin", 95.0, ["janumet"]),
    ("Januvia 100", "Sitagliptin 100mg", ["sitagliptin"], "Diabetes", "15 tablets", 320.0, "Sitagliptin 100mg", 110.0, ["januvia"]),
    ("Istavel 100", "Sitagliptin 100mg", ["sitagliptin"], "Diabetes", "15 tablets", 190.0, "Sitagliptin 100mg", 110.0, ["istavel"]),
    ("Galvus 50", "Vildagliptin 50mg", ["vildagliptin"], "Diabetes", "15 tablets", 250.0, "Vildagliptin 50mg", 80.0, ["galvus"]),
    ("Jardiance 10", "Empagliflozin 10mg", ["empagliflozin"], "Diabetes", "10 tablets", 490.0, "Empagliflozin 10mg", 160.0, ["jardiance"]),
    ("Forxiga 10", "Dapagliflozin 10mg", ["dapagliflozin"], "Diabetes", "14 tablets", 480.0, "Dapagliflozin 10mg", 90.0, ["forxiga"]),
    ("Dapanorm 10", "Dapagliflozin 10mg", ["dapagliflozin"], "Diabetes", "10 tablets", 130.0, "Dapagliflozin 10mg", 90.0, ["dapanorm"]),
    ("Pioz 15", "Pioglitazone 15mg", ["pioglitazone"], "Diabetes", "10 tablets", 95.0, "Pioglitazone 15mg", 30.0, ["pioz"]),
    # ------------------------------------------------------ BP / Cardiac
    ("Telma-AM", "Telmisartan 40mg + Amlodipine 5mg", ["telmisartan", "amlodipine"], "Blood Pressure", "15 tablets", 210.0, "Telmisartan + Amlodipine", 60.0, ["telma am"]),
    ("Telma-H", "Telmisartan 40mg + Hydrochlorothiazide 12.5mg", ["telmisartan", "hydrochlorothiazide"], "Blood Pressure", "15 tablets", 220.0, "Telmisartan + HCTZ", 65.0, ["telma h"]),
    ("Telmikind 40", "Telmisartan 40mg", ["telmisartan"], "Blood Pressure", "10 tablets", 55.0, "Telmisartan 40mg", 25.0, ["telmikind"]),
    ("Losar 50", "Losartan 50mg", ["losartan"], "Blood Pressure", "15 tablets", 120.0, "Losartan 50mg", 35.0, ["losar"]),
    ("Repace 50", "Losartan 50mg", ["losartan"], "Blood Pressure", "15 tablets", 110.0, "Losartan 50mg", 35.0, ["repace"]),
    ("Olmezest 20", "Olmesartan 20mg", ["olmesartan"], "Blood Pressure", "10 tablets", 95.0, "Olmesartan 20mg", 32.0, ["olmezest", "olmy"]),
    ("Stamlo 5", "Amlodipine 5mg", ["amlodipine"], "Blood Pressure", "30 tablets", 65.0, "Amlodipine 5mg", 18.0, ["stamlo"]),
    ("Amlokind 5", "Amlodipine 5mg", ["amlodipine"], "Blood Pressure", "10 tablets", 22.0, "Amlodipine 5mg", 10.0, ["amlokind"]),
    ("Cilacar 10", "Cilnidipine 10mg", ["cilnidipine"], "Blood Pressure", "15 tablets", 165.0, "Cilnidipine 10mg", 55.0, ["cilacar"]),
    ("Concor 5", "Bisoprolol 5mg", ["bisoprolol"], "Heart / BP", "10 tablets", 115.0, "Bisoprolol 5mg", 38.0, ["concor"]),
    ("Met-XL 50", "Metoprolol Succinate 50mg XL", ["metoprolol"], "Heart / BP", "10 tablets", 78.0, "Metoprolol XL 50mg", 28.0, ["met xl", "metxl"]),
    ("Prolomet XL 50", "Metoprolol Succinate 50mg XL", ["metoprolol"], "Heart / BP", "10 tablets", 82.0, "Metoprolol XL 50mg", 28.0, ["prolomet"]),
    ("Betaloc 50", "Metoprolol Tartrate 50mg", ["metoprolol"], "Heart / BP", "10 tablets", 42.0, "Metoprolol 50mg", 16.0, ["betaloc"]),
    ("Nebicard 5", "Nebivolol 5mg", ["nebivolol"], "Heart / BP", "15 tablets", 155.0, "Nebivolol 5mg", 50.0, ["nebicard"]),
    ("Aten 50", "Atenolol 50mg", ["atenolol"], "Heart / BP", "14 tablets", 45.0, "Atenolol 50mg", 15.0, ["aten"]),
    ("Aldactone 25", "Spironolactone 25mg", ["spironolactone"], "Diuretic / Heart", "15 tablets", 55.0, "Spironolactone 25mg", 20.0, ["aldactone"]),
    ("Lasix 40", "Furosemide 40mg", ["furosemide"], "Diuretic", "15 tablets", 25.0, "Furosemide 40mg", 10.0, ["lasix"]),
    ("Dytor 10", "Torsemide 10mg", ["torsemide"], "Diuretic", "15 tablets", 120.0, "Torsemide 10mg", 42.0, ["dytor"]),
    ("Sorbitrate 5", "Isosorbide Dinitrate 5mg", ["isosorbide dinitrate"], "Angina", "50 tablets", 40.0, "Isosorbide Dinitrate 5mg", 18.0, ["sorbitrate"]),
    ("Monotrate 20", "Isosorbide Mononitrate 20mg", ["isosorbide mononitrate"], "Angina", "30 tablets", 90.0, "Isosorbide Mononitrate 20mg", 32.0, ["monotrate"]),
    ("Lanoxin 0.25", "Digoxin 0.25mg", ["digoxin"], "Heart failure / AF", "30 tablets", 45.0, "Digoxin 0.25mg", 20.0, ["lanoxin"]),
    ("Cordarone 200", "Amiodarone 200mg", ["amiodarone"], "Arrhythmia", "10 tablets", 180.0, "Amiodarone 200mg", 65.0, ["cordarone"]),
    ("Ivabrad 5", "Ivabradine 5mg", ["ivabradine"], "Heart failure / Angina", "10 tablets", 210.0, "Ivabradine 5mg", 75.0, ["ivabrad"]),
    # ------------------------------------------- Statins / Antiplatelet / AC
    ("Atorva 10", "Atorvastatin 10mg", ["atorvastatin"], "Cholesterol", "15 tablets", 95.0, "Atorvastatin 10mg", 25.0, ["atorva"]),
    ("Storvas 20", "Atorvastatin 20mg", ["atorvastatin"], "Cholesterol", "15 tablets", 160.0, "Atorvastatin 20mg", 38.0, ["storvas"]),
    ("Lipikind 10", "Atorvastatin 10mg", ["atorvastatin"], "Cholesterol", "10 tablets", 35.0, "Atorvastatin 10mg", 25.0, ["lipikind"]),
    ("Rosuvas 10", "Rosuvastatin 10mg", ["rosuvastatin"], "Cholesterol", "15 tablets", 250.0, "Rosuvastatin 10mg", 55.0, ["rosuvas"]),
    ("Rozavel 10", "Rosuvastatin 10mg", ["rosuvastatin"], "Cholesterol", "15 tablets", 220.0, "Rosuvastatin 10mg", 55.0, ["rozavel"]),
    ("Crestor 10", "Rosuvastatin 10mg", ["rosuvastatin"], "Cholesterol", "10 tablets", 320.0, "Rosuvastatin 10mg", 55.0, ["crestor"]),
    ("Fenolip 160", "Fenofibrate 160mg", ["fenofibrate"], "Cholesterol (triglycerides)", "10 tablets", 165.0, "Fenofibrate 160mg", 58.0, ["fenolip"]),
    ("Clopitab 75", "Clopidogrel 75mg", ["clopidogrel"], "Antiplatelet", "15 tablets", 60.0, "Clopidogrel 75mg", 22.0, ["clopitab"]),
    ("Clavix 75", "Clopidogrel 75mg", ["clopidogrel"], "Antiplatelet", "15 tablets", 65.0, "Clopidogrel 75mg", 22.0, ["clavix"]),
    ("Ecosprin-AV 75", "Aspirin 75mg + Atorvastatin 10mg", ["aspirin", "atorvastatin"], "Antiplatelet + Cholesterol", "10 capsules", 65.0, "Aspirin + Atorvastatin", 25.0, ["ecosprin av"]),
    ("Deplatt-A 75", "Aspirin 75mg + Clopidogrel 75mg", ["aspirin", "clopidogrel"], "Dual antiplatelet", "15 tablets", 90.0, "Aspirin + Clopidogrel", 35.0, ["deplatt a", "deplatt"]),
    ("Xarelto 10", "Rivaroxaban 10mg", ["rivaroxaban"], "Anticoagulant", "10 tablets", 590.0, "Rivaroxaban 10mg", 180.0, ["xarelto"]),
    ("Eliquis 2.5", "Apixaban 2.5mg", ["apixaban"], "Anticoagulant", "10 tablets", 480.0, "Apixaban 2.5mg", 150.0, ["eliquis"]),
    ("Pradaxa 110", "Dabigatran 110mg", ["dabigatran"], "Anticoagulant", "10 capsules", 620.0, "Dabigatran 110mg", 210.0, ["pradaxa"]),
    ("Acitrom 2", "Acenocoumarol 2mg", ["acenocoumarol"], "Anticoagulant", "30 tablets", 190.0, "Acenocoumarol 2mg", 70.0, ["acitrom"]),
    # -------------------------------------------- Respiratory / Allergy / ENT
    ("Cetzine 10", "Cetirizine 10mg", ["cetirizine"], "Allergy", "10 tablets", 28.0, "Cetirizine 10mg", 8.0, ["cetzine", "cetrizine"]),
    ("Okacet 10", "Cetirizine 10mg", ["cetirizine"], "Allergy", "10 tablets", 22.0, "Cetirizine 10mg", 8.0, ["okacet"]),
    ("Alerid 10", "Cetirizine 10mg", ["cetirizine"], "Allergy", "10 tablets", 25.0, "Cetirizine 10mg", 8.0, ["alerid"]),
    ("Allegra 120", "Fexofenadine 120mg", ["fexofenadine"], "Allergy", "10 tablets", 205.0, "Fexofenadine 120mg", 60.0, ["allegra"]),
    ("Teczine 5", "Levocetirizine 5mg", ["levocetirizine"], "Allergy", "10 tablets", 75.0, "Levocetirizine 5mg", 18.0, ["teczine"]),
    ("Levocet 5", "Levocetirizine 5mg", ["levocetirizine"], "Allergy", "10 tablets", 55.0, "Levocetirizine 5mg", 18.0, ["levocet", "lcz"]),
    ("Montek-LC", "Montelukast 10mg + Levocetirizine 5mg", ["montelukast", "levocetirizine"], "Allergy / Asthma", "15 tablets", 260.0, "Montelukast + Levocetirizine", 70.0, ["montek lc", "montek"]),
    ("Avil 25", "Pheniramine 25mg", ["pheniramine"], "Allergy", "15 tablets", 15.0, "Pheniramine 25mg", 8.0, ["avil"]),
    ("Atarax 25", "Hydroxyzine 25mg", ["hydroxyzine"], "Allergy / Itching", "15 tablets", 85.0, "Hydroxyzine 25mg", 30.0, ["atarax"]),
    ("Asthalin 4", "Salbutamol 4mg", ["salbutamol"], "Asthma / COPD", "30 tablets", 22.0, "Salbutamol 4mg", 10.0, ["asthalin"]),
    ("Asthalin Inhaler", "Salbutamol 100mcg/dose", ["salbutamol"], "Asthma / COPD", "200 doses", 165.0, "Salbutamol Inhaler", 90.0, ["asthalin hfa"]),
    ("Levolin 1", "Levosalbutamol 1mg", ["levosalbutamol"], "Asthma / COPD", "10 tablets", 40.0, "Levosalbutamol 1mg", 15.0, ["levolin"]),
    ("Foracort 200", "Budesonide 200mcg + Formoterol 6mcg", ["budesonide", "formoterol"], "Asthma / COPD", "120 doses inhaler", 445.0, "Budesonide + Formoterol Inhaler", 220.0, ["foracort"]),
    ("Budecort 200", "Budesonide 200mcg/dose", ["budesonide"], "Asthma / COPD", "200 doses inhaler", 390.0, "Budesonide Inhaler", 190.0, ["budecort"]),
    ("Duolin", "Levosalbutamol 1.25mg + Ipratropium 500mcg", ["levosalbutamol", "ipratropium"], "Asthma / COPD (nebule)", "5 respules", 105.0, "Levosalbutamol + Ipratropium respules", 48.0, []),
    ("Deriphyllin", "Etofylline 77mg + Theophylline 23mg", ["theophylline", "etofylline"], "Asthma / COPD", "30 tablets", 60.0, "Etofylline + Theophylline", 25.0, ["deriphylline"]),
    ("Ascoril LS", "Ambroxol + Levosalbutamol + Guaifenesin", ["ambroxol", "levosalbutamol", "guaifenesin"], "Cough (wet)", "100 ml syrup", 118.0, "Ambroxol + Levosalbutamol + Guaifenesin syrup", 50.0, ["ascoril"]),
    ("Grilinctus", "Dextromethorphan + Chlorpheniramine", ["dextromethorphan", "chlorpheniramine"], "Cough (dry)", "100 ml syrup", 105.0, "Dextromethorphan + CPM syrup", 45.0, []),
    ("Benadryl", "Diphenhydramine + Ammonium Chloride", ["diphenhydramine"], "Cough", "150 ml syrup", 130.0, "Diphenhydramine cough syrup", 55.0, []),
    ("Sinarest", "Paracetamol 500mg + Phenylephrine 10mg + Chlorpheniramine 2mg", ["paracetamol", "phenylephrine", "chlorpheniramine"], "Cold / Flu", "10 tablets", 60.0, "Paracetamol + Phenylephrine + CPM", 20.0, []),
    ("Cheston Cold", "Cetirizine 5mg + Phenylephrine 10mg + Paracetamol 325mg", ["cetirizine", "phenylephrine", "paracetamol"], "Cold / Flu", "10 tablets", 55.0, "Cetirizine + Phenylephrine + Paracetamol", 18.0, ["cheston"]),
    ("Wikoryl", "Paracetamol + Phenylephrine + Chlorpheniramine", ["paracetamol", "phenylephrine", "chlorpheniramine"], "Cold / Flu", "10 tablets", 58.0, "Paracetamol + Phenylephrine + CPM", 18.0, []),
    ("Otrivin", "Xylometazoline 0.1% nasal drops", ["xylometazoline"], "Nasal congestion", "10 ml drops", 95.0, "Xylometazoline 0.1% drops", 35.0, []),
    ("Mucinac 600", "Acetylcysteine 600mg", ["acetylcysteine"], "Mucolytic", "10 effervescent tablets", 175.0, "Acetylcysteine 600mg", 70.0, ["mucinac"]),
    # ----------------------------------------------------- Thyroid / Hormone
    ("Thyronorm 50", "Levothyroxine 50mcg", ["levothyroxine"], "Thyroid", "120 tablets", 155.0, "Levothyroxine 50mcg", 60.0, ["thyronorm"]),
    ("Eltroxin 50", "Levothyroxine 50mcg", ["levothyroxine"], "Thyroid", "100 tablets", 140.0, "Levothyroxine 50mcg", 60.0, ["eltroxin"]),
    ("Neo-Mercazole 5", "Carbimazole 5mg", ["carbimazole"], "Hyperthyroid", "30 tablets", 90.0, "Carbimazole 5mg", 35.0, ["neomercazole", "neo mercazole"]),
    # ------------------------------------------------------ Neuro / Psych
    ("Nexito 10", "Escitalopram 10mg", ["escitalopram"], "Depression / Anxiety", "10 tablets", 110.0, "Escitalopram 10mg", 32.0, ["nexito"]),
    ("Cipralex 10", "Escitalopram 10mg", ["escitalopram"], "Depression / Anxiety", "10 tablets", 130.0, "Escitalopram 10mg", 32.0, ["cipralex"]),
    ("Daxid 50", "Sertraline 50mg", ["sertraline"], "Depression / Anxiety", "10 tablets", 105.0, "Sertraline 50mg", 30.0, ["daxid"]),
    ("Zosert 50", "Sertraline 50mg", ["sertraline"], "Depression / Anxiety", "10 tablets", 85.0, "Sertraline 50mg", 30.0, ["zosert"]),
    ("Prodep 20", "Fluoxetine 20mg", ["fluoxetine"], "Depression", "10 capsules", 45.0, "Fluoxetine 20mg", 16.0, ["prodep", "fludac"]),
    ("Veniz XR 75", "Venlafaxine 75mg XR", ["venlafaxine"], "Depression / Anxiety", "10 capsules", 160.0, "Venlafaxine XR 75mg", 55.0, ["veniz"]),
    ("Mirtaz 15", "Mirtazapine 15mg", ["mirtazapine"], "Depression / Sleep", "10 tablets", 130.0, "Mirtazapine 15mg", 45.0, ["mirtaz"]),
    ("Trika 0.25", "Alprazolam 0.25mg", ["alprazolam"], "Anxiety / Sleep", "15 tablets", 32.0, "Alprazolam 0.25mg", 12.0, ["trika"]),
    ("Restyl 0.25", "Alprazolam 0.25mg", ["alprazolam"], "Anxiety / Sleep", "15 tablets", 35.0, "Alprazolam 0.25mg", 12.0, ["restyl"]),
    ("Lopez 2", "Lorazepam 2mg", ["lorazepam"], "Anxiety / Sleep", "10 tablets", 40.0, "Lorazepam 2mg", 15.0, ["lopez", "ativan"]),
    ("Zolfresh 10", "Zolpidem 10mg", ["zolpidem"], "Insomnia", "10 tablets", 105.0, "Zolpidem 10mg", 35.0, ["zolfresh"]),
    ("Clonotril 0.5", "Clonazepam 0.5mg", ["clonazepam"], "Anxiety / Seizure", "15 tablets", 42.0, "Clonazepam 0.5mg", 15.0, ["clonotril", "rivotril"]),
    ("Eptoin 100", "Phenytoin 100mg", ["phenytoin"], "Epilepsy", "120 tablets", 145.0, "Phenytoin 100mg", 60.0, ["eptoin"]),
    ("Tegrital 200", "Carbamazepine 200mg", ["carbamazepine"], "Epilepsy / Neuralgia", "10 tablets", 35.0, "Carbamazepine 200mg", 14.0, ["tegrital"]),
    ("Encorate Chrono 300", "Sodium Valproate 200mg + Valproic Acid 87mg", ["valproate"], "Epilepsy", "10 tablets", 75.0, "Sodium Valproate CR 300mg", 30.0, ["encorate", "valparin"]),
    ("Levipil 500", "Levetiracetam 500mg", ["levetiracetam"], "Epilepsy", "10 tablets", 125.0, "Levetiracetam 500mg", 45.0, ["levipil", "keppra"]),
    ("Lamitor 50", "Lamotrigine 50mg", ["lamotrigine"], "Epilepsy / Mood", "10 tablets", 85.0, "Lamotrigine 50mg", 32.0, ["lamitor"]),
    ("Gabapin 300", "Gabapentin 300mg", ["gabapentin"], "Nerve pain", "10 capsules", 175.0, "Gabapentin 300mg", 60.0, ["gabapin"]),
    ("Pregabid 75", "Pregabalin 75mg", ["pregabalin"], "Nerve pain", "10 capsules", 160.0, "Pregabalin 75mg", 50.0, ["pregabid", "lyrica"]),
    ("Suminat 50", "Sumatriptan 50mg", ["sumatriptan"], "Migraine (acute)", "5 tablets", 260.0, "Sumatriptan 50mg", 95.0, ["suminat"]),
    ("Sibelium 10", "Flunarizine 10mg", ["flunarizine"], "Migraine (prevention)", "10 tablets", 180.0, "Flunarizine 10mg", 60.0, ["sibelium"]),
    ("Vertin 16", "Betahistine 16mg", ["betahistine"], "Vertigo", "15 tablets", 190.0, "Betahistine 16mg", 60.0, ["vertin", "betavert"]),
    ("Stugeron 25", "Cinnarizine 25mg", ["cinnarizine"], "Vertigo / Motion sickness", "15 tablets", 65.0, "Cinnarizine 25mg", 25.0, ["stugeron"]),
    ("Stemetil 5", "Prochlorperazine 5mg", ["prochlorperazine"], "Vertigo / Nausea", "20 tablets", 60.0, "Prochlorperazine 5mg", 25.0, ["stemetil"]),
    ("Avomine 25", "Promethazine 25mg", ["promethazine"], "Motion sickness", "10 tablets", 40.0, "Promethazine 25mg", 16.0, ["avomine"]),
    ("Pacitane 2", "Trihexyphenidyl 2mg", ["trihexyphenidyl"], "Parkinsonism", "30 tablets", 45.0, "Trihexyphenidyl 2mg", 18.0, ["pacitane"]),
    ("Syndopa Plus", "Levodopa 100mg + Carbidopa 25mg", ["levodopa", "carbidopa"], "Parkinson's", "30 tablets", 110.0, "Levodopa + Carbidopa", 45.0, ["syndopa"]),
    ("Donep 5", "Donepezil 5mg", ["donepezil"], "Dementia", "10 tablets", 95.0, "Donepezil 5mg", 35.0, ["donep"]),
    # ------------------------------------------------- Steroid / Immune
    ("Wysolone 10", "Prednisolone 10mg", ["prednisolone"], "Steroid", "15 tablets", 55.0, "Prednisolone 10mg", 20.0, ["wysolone"]),
    ("Omnacortil 10", "Prednisolone 10mg", ["prednisolone"], "Steroid", "10 tablets", 38.0, "Prednisolone 10mg", 20.0, ["omnacortil"]),
    ("Medrol 8", "Methylprednisolone 8mg", ["methylprednisolone"], "Steroid", "10 tablets", 105.0, "Methylprednisolone 8mg", 38.0, ["medrol"]),
    ("Betnesol 0.5", "Betamethasone 0.5mg", ["betamethasone"], "Steroid", "20 tablets", 18.0, "Betamethasone 0.5mg", 9.0, ["betnesol"]),
    ("Dexona 0.5", "Dexamethasone 0.5mg", ["dexamethasone"], "Steroid", "30 tablets", 12.0, "Dexamethasone 0.5mg", 6.0, ["dexona"]),
    ("Folitrax 7.5", "Methotrexate 7.5mg", ["methotrexate"], "Rheumatoid arthritis / Psoriasis", "10 tablets", 130.0, "Methotrexate 7.5mg", 50.0, ["folitrax"]),
    ("HCQS 200", "Hydroxychloroquine 200mg", ["hydroxychloroquine"], "Rheumatoid arthritis / Lupus", "15 tablets", 105.0, "Hydroxychloroquine 200mg", 40.0, ["hcqs"]),
    ("Saaz 500", "Sulfasalazine 500mg", ["sulfasalazine"], "Rheumatoid arthritis / IBD", "10 tablets", 90.0, "Sulfasalazine 500mg", 35.0, ["saaz"]),
    # ---------------------------------------------------------- Gout
    ("Zyloric 100", "Allopurinol 100mg", ["allopurinol"], "Gout", "10 tablets", 40.0, "Allopurinol 100mg", 15.0, ["zyloric"]),
    ("Feburic 40", "Febuxostat 40mg", ["febuxostat"], "Gout", "10 tablets", 105.0, "Febuxostat 40mg", 38.0, ["feburic", "zurig"]),
    ("Goutnil 0.5", "Colchicine 0.5mg", ["colchicine"], "Gout (acute)", "10 tablets", 60.0, "Colchicine 0.5mg", 25.0, ["goutnil", "zycolchin"]),
    # ---------------------------------------------- Muscle relaxant
    ("Myoril 4", "Thiocolchicoside 4mg", ["thiocolchicoside"], "Muscle spasm", "10 capsules", 260.0, "Thiocolchicoside 4mg", 90.0, ["myoril"]),
    ("Myospaz", "Chlorzoxazone 250mg + Paracetamol 300mg", ["chlorzoxazone", "paracetamol"], "Muscle spasm", "10 tablets", 90.0, "Chlorzoxazone + Paracetamol", 32.0, []),
    ("Sirdalud 2", "Tizanidine 2mg", ["tizanidine"], "Muscle spasm", "10 tablets", 130.0, "Tizanidine 2mg", 45.0, ["sirdalud"]),
    ("Liofen 10", "Baclofen 10mg", ["baclofen"], "Muscle spasm", "10 tablets", 85.0, "Baclofen 10mg", 30.0, ["liofen"]),
    # ------------------------------------------- Antifungal / -viral / -parasitic
    ("Forcan 150", "Fluconazole 150mg", ["fluconazole"], "Antifungal", "1 tablet", 20.0, "Fluconazole 150mg", 8.0, ["forcan", "fluka"]),
    ("Zocon 150", "Fluconazole 150mg", ["fluconazole"], "Antifungal", "1 tablet", 22.0, "Fluconazole 150mg", 8.0, ["zocon"]),
    ("Candiforce 200", "Itraconazole 200mg", ["itraconazole"], "Antifungal", "10 capsules", 320.0, "Itraconazole 200mg", 120.0, ["candiforce", "itraz"]),
    ("Sebifin 250", "Terbinafine 250mg", ["terbinafine"], "Antifungal", "7 tablets", 175.0, "Terbinafine 250mg", 65.0, ["sebifin", "terbicip"]),
    ("Grisovin FP 250", "Griseofulvin 250mg", ["griseofulvin"], "Antifungal", "10 tablets", 85.0, "Griseofulvin 250mg", 35.0, ["grisovin"]),
    ("Zentel 400", "Albendazole 400mg", ["albendazole"], "Deworming", "1 tablet", 12.0, "Albendazole 400mg", 6.0, ["zentel", "bandy"]),
    ("Ivecop 12", "Ivermectin 12mg", ["ivermectin"], "Antiparasitic", "1 tablet", 32.0, "Ivermectin 12mg", 14.0, ["ivecop"]),
    ("Acivir 400", "Acyclovir 400mg", ["acyclovir"], "Antiviral (herpes)", "10 tablets", 140.0, "Acyclovir 400mg", 55.0, ["acivir", "zovirax"]),
    ("Valcivir 500", "Valacyclovir 500mg", ["valacyclovir"], "Antiviral (herpes/zoster)", "10 tablets", 380.0, "Valacyclovir 500mg", 140.0, ["valcivir"]),
    ("Lariago 250", "Chloroquine 250mg", ["chloroquine"], "Antimalarial", "10 tablets", 18.0, "Chloroquine 250mg", 9.0, ["lariago"]),
    ("Fluvir 75", "Oseltamivir 75mg", ["oseltamivir"], "Antiviral (flu)", "10 capsules", 460.0, "Oseltamivir 75mg", 180.0, ["fluvir", "tamiflu"]),
    # ------------------------------------------------ Supplements / Vitamins
    ("Shelcal 500", "Calcium Carbonate 1250mg + Vitamin D3 250IU", ["calcium carbonate", "vitamin d3"], "Calcium supplement", "15 tablets", 105.0, "Calcium + D3", 35.0, ["shelcal"]),
    ("Calcirol 60K", "Cholecalciferol 60000IU", ["vitamin d3"], "Vitamin D", "4 sachets", 130.0, "Cholecalciferol 60000IU", 40.0, ["calcirol"]),
    ("Uprise-D3 60K", "Cholecalciferol 60000IU", ["vitamin d3"], "Vitamin D", "4 capsules", 118.0, "Cholecalciferol 60000IU", 40.0, ["uprise d3", "d rise"]),
    ("Zincovit", "Multivitamin + Multimineral + Zinc", ["multivitamin"], "Multivitamin", "15 tablets", 105.0, "Multivitamin + Zinc", 35.0, []),
    ("Becosules", "B-Complex + Vitamin C", ["b-complex"], "Vitamin B", "20 capsules", 55.0, "B-Complex + Vitamin C", 20.0, ["becosule"]),
    ("A to Z NS", "Multivitamin + Minerals", ["multivitamin"], "Multivitamin", "15 tablets", 110.0, "Multivitamin + Minerals", 35.0, ["a to z"]),
    ("Neurobion Forte", "Vitamin B1 + B6 + B12", ["b-complex"], "Vitamin B (nerve)", "30 tablets", 40.0, "B1 + B6 + B12", 18.0, ["neurobion"]),
    ("Nurokind Plus", "Methylcobalamin 1500mcg + ALA + B-vitamins", ["methylcobalamin"], "Vitamin B12 (nerve)", "10 capsules", 110.0, "Methylcobalamin combo", 40.0, ["nurokind"]),
    ("Evion 400", "Vitamin E 400mg", ["vitamin e"], "Vitamin E", "10 capsules", 35.0, "Vitamin E 400mg", 16.0, ["evion"]),
    ("Livogen", "Ferrous Fumarate 152mg + Folic Acid 1.5mg", ["iron", "folic acid"], "Iron / Anaemia", "15 tablets", 50.0, "Iron + Folic Acid", 18.0, []),
    ("Orofer-XT", "Ferrous Ascorbate 100mg + Folic Acid 1.5mg", ["iron", "folic acid"], "Iron / Anaemia", "10 tablets", 115.0, "Ferrous Ascorbate + Folic Acid", 38.0, ["orofer xt", "orofer"]),
    ("Autrin", "Ferrous Fumarate + Folic Acid + B12 + Vitamin C", ["iron", "folic acid"], "Iron / Anaemia", "30 capsules", 110.0, "Iron + Folic Acid + B12", 40.0, []),
    ("Folvite 5", "Folic Acid 5mg", ["folic acid"], "Folic acid", "45 tablets", 55.0, "Folic Acid 5mg", 20.0, ["folvite"]),
    ("Limcee 500", "Vitamin C 500mg", ["vitamin c"], "Vitamin C", "15 tablets", 25.0, "Vitamin C 500mg", 12.0, ["limcee", "celin"]),
    # ------------------------------------------------------- Urology / Men
    ("Urimax 0.4", "Tamsulosin 0.4mg", ["tamsulosin"], "Prostate (BPH)", "15 capsules", 260.0, "Tamsulosin 0.4mg", 80.0, ["urimax"]),
    ("Veltam 0.4", "Tamsulosin 0.4mg", ["tamsulosin"], "Prostate (BPH)", "15 tablets", 230.0, "Tamsulosin 0.4mg", 80.0, ["veltam"]),
    ("Silodal 8", "Silodosin 8mg", ["silodosin"], "Prostate (BPH)", "10 capsules", 270.0, "Silodosin 8mg", 95.0, ["silodal"]),
    ("Alfoo 10", "Alfuzosin 10mg", ["alfuzosin"], "Prostate (BPH)", "15 tablets", 240.0, "Alfuzosin 10mg", 85.0, ["alfoo"]),
    ("Fincar 5", "Finasteride 5mg", ["finasteride"], "Prostate (BPH)", "10 tablets", 95.0, "Finasteride 5mg", 35.0, ["fincar", "finast"]),
    ("Manforce 50", "Sildenafil 50mg", ["sildenafil"], "Erectile dysfunction", "4 tablets", 105.0, "Sildenafil 50mg", 40.0, ["manforce", "suhagra", "viagra"]),
    ("Megalis 10", "Tadalafil 10mg", ["tadalafil"], "Erectile dysfunction", "4 tablets", 165.0, "Tadalafil 10mg", 60.0, ["megalis", "tadacip"]),
    ("Niftas 100", "Nitrofurantoin 100mg", ["nitrofurantoin"], "Urinary infection", "10 tablets", 190.0, "Nitrofurantoin 100mg", 70.0, ["niftas"]),
    ("Citralka", "Disodium Hydrogen Citrate 1.4g/5ml", ["disodium hydrogen citrate"], "Urinary alkalizer", "100 ml syrup", 105.0, "Disodium Hydrogen Citrate syrup", 45.0, []),
    # --------------------------------------------------- Women's health
    ("Duphaston 10", "Dydrogesterone 10mg", ["dydrogesterone"], "Hormone (progesterone)", "10 tablets", 620.0, "Dydrogesterone 10mg", 230.0, ["duphaston"]),
    ("Susten 200", "Micronized Progesterone 200mg", ["progesterone"], "Hormone (progesterone)", "10 capsules", 390.0, "Progesterone 200mg", 150.0, ["susten"]),
    ("Meprate 10", "Medroxyprogesterone 10mg", ["medroxyprogesterone"], "Hormone", "10 tablets", 60.0, "Medroxyprogesterone 10mg", 25.0, ["meprate", "deviry"]),
    ("Regestrone 5", "Norethisterone 5mg", ["norethisterone"], "Hormone", "10 tablets", 55.0, "Norethisterone 5mg", 22.0, ["regestrone", "primolut n"]),
    ("Krimson 35", "Ethinylestradiol 35mcg + Cyproterone 2mg", ["ethinylestradiol", "cyproterone"], "PCOS / Contraceptive", "21 tablets", 380.0, "EE + Cyproterone", 140.0, ["krimson"]),
    ("Ovral-L", "Ethinylestradiol 30mcg + Levonorgestrel 0.15mg", ["ethinylestradiol", "levonorgestrel"], "Contraceptive", "21 tablets", 120.0, "EE + Levonorgestrel", 50.0, ["ovral l", "ovral"]),
    ("Fertyl 50", "Clomiphene Citrate 50mg", ["clomiphene"], "Ovulation induction", "5 tablets", 60.0, "Clomiphene 50mg", 25.0, ["fertyl"]),
    # -------------------------------------------------- Skin / Topical
    ("Betnovate-N", "Betamethasone + Neomycin cream", ["betamethasone", "neomycin"], "Skin (steroid + antibiotic)", "20 g cream", 45.0, "Betamethasone + Neomycin cream", 20.0, ["betnovate n", "betnovate"]),
    ("Candid Cream", "Clotrimazole 1% cream", ["clotrimazole"], "Skin antifungal", "30 g cream", 105.0, "Clotrimazole 1% cream", 40.0, ["candid"]),
    ("Luliconazole Cream", "Luliconazole 1% cream", ["luliconazole"], "Skin antifungal", "30 g cream", 220.0, "Luliconazole 1% cream", 85.0, ["lulifin", "luliford"]),
    ("Permite", "Permethrin 5% cream", ["permethrin"], "Scabies", "30 g cream", 90.0, "Permethrin 5% cream", 40.0, []),
    ("Retino-A 0.025", "Tretinoin 0.025% cream", ["tretinoin"], "Acne", "20 g cream", 165.0, "Tretinoin 0.025% cream", 65.0, ["retino a"]),
    # -------------------------------------------------------- Misc
    ("Zyrcold Plus", "Paracetamol + Phenylephrine + Cetirizine", ["paracetamol", "phenylephrine", "cetirizine"], "Cold / Flu", "10 tablets", 52.0, "Paracetamol + Phenylephrine + Cetirizine", 18.0, ["zyrcold"]),
    ("Digene", "Antacid gel (Mg/Al hydroxide + Simethicone)", ["antacid"], "Acidity (instant relief)", "170 ml gel", 125.0, "Antacid gel", 50.0, []),
    ("Gelusil MPS", "Antacid (Mg/Al hydroxide + Simethicone)", ["antacid"], "Acidity (instant relief)", "200 ml syrup", 140.0, "Antacid gel", 50.0, ["gelusil"]),
    ("Electral", "Oral Rehydration Salts (WHO-ORS)", ["ors"], "Dehydration", "21.8 g sachet", 22.0, "ORS sachet", 12.0, ["ors"]),
    ("Enzoflam", "Diclofenac 50mg + Paracetamol 325mg + Serratiopeptidase 15mg", ["diclofenac", "paracetamol", "serratiopeptidase"], "Pain / Inflammation", "10 tablets", 120.0, "Diclofenac + Paracetamol + Serratiopeptidase", 42.0, []),
    ("Chymoral Forte", "Trypsin-Chymotrypsin 100000 AU", ["trypsin-chymotrypsin"], "Swelling / Healing", "20 tablets", 380.0, "Trypsin-Chymotrypsin", 140.0, ["chymoral"]),
    ("Signoflam", "Aceclofenac + Paracetamol + Serratiopeptidase", ["aceclofenac", "paracetamol", "serratiopeptidase"], "Pain / Inflammation", "10 tablets", 105.0, "Aceclofenac + Paracetamol + Serratiopeptidase", 38.0, []),
]

# New interaction rules for salts introduced above.
NEW_RULES = [
    (["sildenafil", "isosorbide dinitrate"], "major", "PDE5 inhibitors with nitrates cause severe, potentially fatal blood-pressure drop.", "Never combine. Seek emergency care if chest pain occurs after taking both."),
    (["sildenafil", "isosorbide mononitrate"], "major", "PDE5 inhibitors with nitrates cause severe, potentially fatal blood-pressure drop.", "Never combine. Seek emergency care if chest pain occurs after taking both."),
    (["tadalafil", "isosorbide dinitrate"], "major", "PDE5 inhibitors with nitrates cause severe, potentially fatal blood-pressure drop.", "Never combine. Seek emergency care if chest pain occurs after taking both."),
    (["tadalafil", "isosorbide mononitrate"], "major", "PDE5 inhibitors with nitrates cause severe, potentially fatal blood-pressure drop.", "Never combine. Seek emergency care if chest pain occurs after taking both."),
    (["methotrexate", "ibuprofen"], "major", "NSAIDs reduce methotrexate clearance, risking serious toxicity (mouth ulcers, low blood counts).", "Avoid regular NSAID use on methotrexate; consult the rheumatologist."),
    (["methotrexate", "diclofenac"], "major", "NSAIDs reduce methotrexate clearance, risking serious toxicity.", "Avoid regular NSAID use on methotrexate; consult the rheumatologist."),
    (["methotrexate", "aceclofenac"], "major", "NSAIDs reduce methotrexate clearance, risking serious toxicity.", "Avoid regular NSAID use on methotrexate; consult the rheumatologist."),
    (["methotrexate", "aspirin"], "major", "Aspirin reduces methotrexate clearance, risking serious toxicity.", "Avoid combining without specialist guidance."),
    (["colchicine", "clarithromycin"], "major", "Clarithromycin blocks colchicine breakdown — reported fatal colchicine toxicity.", "Combination should be avoided; ask the doctor for an alternative antibiotic."),
    (["atorvastatin", "clarithromycin"], "major", "Clarithromycin sharply raises statin levels — risk of muscle breakdown (rhabdomyolysis).", "Statin is usually paused during the clarithromycin course."),
    (["rosuvastatin", "clarithromycin"], "moderate", "Clarithromycin can raise statin exposure — muscle injury risk.", "Report muscle pain or dark urine promptly."),
    (["atorvastatin", "fenofibrate"], "moderate", "Statin + fibrate increases risk of muscle injury.", "Often co-prescribed deliberately — report unexplained muscle pain."),
    (["rosuvastatin", "fenofibrate"], "moderate", "Statin + fibrate increases risk of muscle injury.", "Often co-prescribed deliberately — report unexplained muscle pain."),
    (["fluconazole", "atorvastatin"], "moderate", "Fluconazole raises statin levels — muscle injury risk.", "Usually fine for single-dose fluconazole; caution with longer courses."),
    (["fluconazole", "warfarin"], "major", "Fluconazole strongly potentiates warfarin — bleeding risk.", "INR must be monitored; dose adjustment often needed."),
    (["fluconazole", "domperidone"], "moderate", "Both prolong the QT interval — heart rhythm risk.", "Avoid combining in heart patients; watch for palpitations or fainting."),
    (["ciprofloxacin", "tizanidine"], "major", "Ciprofloxacin massively raises tizanidine levels — severe drowsiness and BP drop.", "Contraindicated combination; ask for a different antibiotic or muscle relaxant."),
    (["ciprofloxacin", "theophylline"], "major", "Ciprofloxacin raises theophylline levels — nausea, tremor, seizures possible.", "Needs dose reduction and monitoring; tell the doctor you take Deriphyllin."),
    (["spironolactone", "ramipril"], "moderate", "ACE inhibitor + potassium-sparing diuretic can cause dangerous potassium rise.", "Common combo in heart failure but needs periodic potassium blood tests."),
    (["spironolactone", "telmisartan"], "moderate", "ARB + potassium-sparing diuretic can cause dangerous potassium rise.", "Needs periodic potassium blood tests."),
    (["spironolactone", "losartan"], "moderate", "ARB + potassium-sparing diuretic can cause dangerous potassium rise.", "Needs periodic potassium blood tests."),
    (["digoxin", "amiodarone"], "major", "Amiodarone raises digoxin levels — toxicity (nausea, vision changes, arrhythmia).", "Digoxin dose is usually halved; levels must be monitored."),
    (["digoxin", "clarithromycin"], "major", "Clarithromycin raises digoxin levels — toxicity risk.", "Monitor for nausea, confusion, palpitations; inform the doctor."),
    (["sumatriptan", "escitalopram"], "moderate", "Triptan + SSRI: small risk of serotonin syndrome.", "Watch for agitation, sweating, tremor after dosing together."),
    (["sumatriptan", "sertraline"], "moderate", "Triptan + SSRI: small risk of serotonin syndrome.", "Watch for agitation, sweating, tremor after dosing together."),
    (["escitalopram", "ibuprofen"], "moderate", "SSRIs + NSAIDs increase stomach bleeding risk.", "Prefer paracetamol; add a PPI if NSAID is unavoidable."),
    (["sertraline", "ibuprofen"], "moderate", "SSRIs + NSAIDs increase stomach bleeding risk.", "Prefer paracetamol; add a PPI if NSAID is unavoidable."),
    (["escitalopram", "aspirin"], "moderate", "SSRIs + aspirin increase stomach bleeding risk.", "Often co-prescribed; watch for black stools, add gastro-protection."),
    (["doxycycline", "calcium carbonate"], "moderate", "Calcium binds doxycycline and blocks its absorption.", "Separate doses by at least 2–3 hours."),
    (["doxycycline", "iron"], "moderate", "Iron binds doxycycline and blocks its absorption.", "Separate doses by at least 2–3 hours."),
    (["ciprofloxacin", "calcium carbonate"], "moderate", "Calcium binds ciprofloxacin and reduces its effect.", "Take the antibiotic 2 hours before or 6 hours after calcium."),
    (["ciprofloxacin", "iron"], "moderate", "Iron binds ciprofloxacin and reduces its effect.", "Take the antibiotic 2 hours before or 6 hours after iron."),
    (["levofloxacin", "calcium carbonate"], "moderate", "Calcium binds levofloxacin and reduces its effect.", "Separate doses by several hours."),
    (["hydroxychloroquine", "azithromycin"], "moderate", "Both prolong the QT interval — heart rhythm risk.", "Caution in cardiac patients; ECG monitoring if combined long-term."),
    (["tramadol", "fluoxetine"], "major", "Risk of serotonin syndrome and lowered seizure threshold.", "Combination needs medical supervision."),
    (["tramadol", "venlafaxine"], "major", "Risk of serotonin syndrome and lowered seizure threshold.", "Combination needs medical supervision."),
    (["zolpidem", "lorazepam"], "major", "Combined CNS depression — excessive sedation, impaired breathing, falls.", "Avoid taking together; never combine with alcohol."),
    (["clonazepam", "zolpidem"], "major", "Combined CNS depression — excessive sedation, impaired breathing, falls.", "Avoid taking together; never combine with alcohol."),
    (["carbamazepine", "clarithromycin"], "major", "Clarithromycin raises carbamazepine to toxic levels (dizziness, double vision).", "Needs level monitoring or an alternative antibiotic."),
    (["phenytoin", "fluconazole"], "major", "Fluconazole raises phenytoin levels — toxicity risk.", "Levels should be monitored if combined."),
    (["valproate", "carbapenem"], "major", "Carbapenem antibiotics drastically drop valproate levels — seizure risk.", "Combination generally avoided."),
    (["levothyroxine", "omeprazole"], "moderate", "Long-term acid suppression can reduce thyroxine absorption.", "Take thyroxine on an empty stomach; recheck TSH if PPI is chronic."),
    (["prednisolone", "ibuprofen"], "moderate", "Steroids + NSAIDs multiply stomach ulcer and bleeding risk.", "Avoid casual NSAID use on steroids; add a PPI if needed."),
    (["prednisolone", "diclofenac"], "moderate", "Steroids + NSAIDs multiply stomach ulcer and bleeding risk.", "Avoid casual NSAID use on steroids; add a PPI if needed."),
    (["metformin", "furosemide"], "moderate", "Loop diuretics can affect kidney function and metformin clearance.", "Kidney function should be checked periodically."),
    (["allopurinol", "amoxicillin"], "moderate", "Higher chance of skin rash when combined.", "Report any rash promptly."),
    (["nimesulide", "paracetamol"], "moderate", "Both stress the liver; several combos double-dose paracetamol unknowingly.", "Avoid alcohol; do not exceed 3g paracetamol/day in total."),
]


def slugify_aliases(brand: str, extra: list[str]) -> list[str]:
    """Auto-generate obvious lookup aliases for a brand name."""
    b = brand.lower()
    aliases = {b}
    no_dose = re.sub(r"[\s-]*\d+[\w./]*$", "", b).strip()
    if no_dose and no_dose != b:
        aliases.add(no_dose)
    aliases.update(a.lower() for a in extra)
    aliases.discard(b)  # brand itself is already indexed
    return sorted(aliases)


def main() -> None:
    meds = json.loads((HERE / "medicines.json").read_text(encoding="utf-8"))
    known = {e["brand"].lower() for e in meds["brands"]}

    added = 0
    for brand, salt, keys, cat, pack, bp, gname, gp, extra in NEW_BRANDS:
        if brand.lower() in known:
            continue
        meds["brands"].append({
            "brand": brand,
            "salt": salt,
            "salt_keys": keys,
            "category": cat,
            "pack": pack,
            "brand_price": bp,
            "generic": {"name": gname, "price": gp},
            "aliases": slugify_aliases(brand, extra),
        })
        known.add(brand.lower())
        added += 1

    meds["brands"].sort(key=lambda e: (e["category"], e["brand"]))
    (HERE / "medicines.json").write_text(
        json.dumps(meds, indent=2, ensure_ascii=False), encoding="utf-8")

    inter = json.loads((HERE / "interactions.json").read_text(encoding="utf-8"))
    known_pairs = {frozenset(s.lower() for s in r["salts"]) for r in inter["interactions"]}
    added_rules = 0
    for salts, sev, effect, advice in NEW_RULES:
        if frozenset(salts) in known_pairs:
            continue
        inter["interactions"].append(
            {"salts": salts, "severity": sev, "effect": effect, "advice": advice})
        known_pairs.add(frozenset(salts))
        added_rules += 1

    (HERE / "interactions.json").write_text(
        json.dumps(inter, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"medicines: +{added} new -> {len(meds['brands'])} total")
    print(f"interactions: +{added_rules} new -> {len(inter['interactions'])} total")


if __name__ == "__main__":
    main()

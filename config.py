# config.py

# SFoC verileri (load-% : g/kWh) - Sabit veri
sfoc_data_global = {
    25: 205,
    50: 186,
    75: 178,
    85: 175,
    100: 178
}

CONVENTIONAL_SHAFT_EFFICIENCY = 0.95 
                                    
PROPULSION_PATH_INV_EFFICIENCY = 0.95 / 0.93

# Ana Makine (Geleneksel Tahrik) için SFOC Verileri (load-% : g/kWh)
SFOC_DATA_MAIN_ENGINE = {
    25: 215,  # Örnek değerler
    50: 195,
    75: 186,
    85: 184,
    100: 186
}

# Ana Dizel Jeneratörler (DE Sistemindeki büyük jeneratörler) için SFOC Verileri
SFOC_DATA_MAIN_DE_GEN = {
    25: 210,
    50: 190,
    75: 183,
    85: 181,
    100: 183
}

# Liman Jeneratörü (DE Sistemindeki küçük yardımcı/manevra jeneratörü) için SFOC Verileri
SFOC_DATA_PORT_GEN = {
    25: 213,
    50: 194,
    75: 188,
    85: 183,
    100: 185
}

# Yardımcı Dizel Jeneratörler (Geleneksel sistemin manevradaki yardımcıları) için SFOC Verileri
SFOC_DATA_AUX_DG = {
    25: 213,
    50: 194,
    75: 188,
    85: 183,
    100: 185
}

# Tüm SFOC eğrilerini bir arada tutan bir sözlük (get_best_combination'a geçmek için faydalı olabilir)
ALL_SFOC_CURVES = {
    "main_engine": SFOC_DATA_MAIN_ENGINE,
    "main_de_gen": SFOC_DATA_MAIN_DE_GEN,
    "port_gen": SFOC_DATA_PORT_GEN,
    "aux_dg": SFOC_DATA_AUX_DG
}
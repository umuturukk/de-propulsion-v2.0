# app.py
import streamlit as st

# Sayfa modüllerini import et
import fuel_analysis_page
import new_combinations_page

# --- Streamlit Sayfa Ayarları ---
st.set_page_config(
    page_title="Gemi Yakıt Analiz Aracı", # Tarayıcı sekmesinde görünecek başlık
    page_icon="🚢",                    # Tarayıcı sekmesinde görünecek ikon
    layout="wide",                       # Sayfa düzeni: "centered" veya "wide"
    initial_sidebar_state="expanded"     # Sidebar başlangıç durumu: "auto", "expanded", "collapsed"
)

# --- Ana Sayfa Navigasyonu ---
# Streamlit'in yerel çoklu sayfa (multipage app) desteği için `pages/` klasörü ve
# oradaki Python dosyaları kullanılabilir. Bu, sidebar'da otomatik navigasyon oluşturur.
# Ancak, mevcut kodunuzdaki radio butonlu sayfa seçimi korunmuştur.

page_options = {
    "Dizel Elektrik vs Geleneksel Sistem": fuel_analysis_page,
    "Dizel Elektrik Sistemi (Küçük Jeneratör ile)": new_combinations_page
}

st.sidebar.title("Dizel Elektrik Tahrik Sistemi")
selected_page_name = st.sidebar.radio(
    "Sayfa seçimi:",
    list(page_options.keys()),
    key="main_page_selector_radio" # Benzersiz bir anahtar
)

# Seçilen sayfayı render et
if selected_page_name in page_options:
    page_module = page_options[selected_page_name]
    page_module.render_page() # Her sayfa modülünde render_page() fonksiyonu olmalı
else:
    st.error("Geçersiz sayfa seçimi!")


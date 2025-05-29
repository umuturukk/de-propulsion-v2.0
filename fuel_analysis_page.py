# fuel_analysis_page.py
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import graphviz # Eğer graphviz kurulu değilse: pip install graphviz streamlit-agraph

# Proje içi modüllerden importlar
# DEĞİŞİKLİK: İlgili SFOC verileri doğrudan import ediliyor
from config import (
    SFOC_DATA_MAIN_ENGINE,
    SFOC_DATA_AUX_DG,
    SFOC_DATA_MAIN_DE_GEN,
    SFOC_DATA_PORT_GEN,
    ALL_SFOC_CURVES
)
from core_calculations import (
    determine_generator_usage,
    interpolate_sfoc_non_linear, # SFOC eğrisi çizimi için
    calculate_fuel,
    calculate_power_flow      # Güç akış diyagramı için
)

def render_page():
    """ "Yakıt Analizi" sayfasının içeriğini ve mantığını render eder. """
    st.sidebar.header("Yakıt Analizi Girdi Ayarları")
    # Widget'lar için benzersiz key'ler (önemli!)
    gen_power_range_input = st.sidebar.slider("Jeneratör Birim Güç Aralığı (kW)", 1800, 3600, (2000, 3400), step=100, key="fa_gen_power_range")
    sea_power_range_input = st.sidebar.slider("Seyir Şaft Güç Aralığı (kW)", 2500, 5500, (3000, 4400), step=100, key="fa_sea_power_range")
    maneuver_power_range_input = st.sidebar.slider("Manevra Şaft Güç Aralığı (kW)", 1500, 3500, (1600, 2700), step=100, key="fa_maneuver_power_range")
    sea_duration_input = st.sidebar.number_input("Seyir Süresi (saat)", min_value=1.0, value=48.0, step=1.0, key="fa_sea_duration")
    maneuver_duration_input = st.sidebar.number_input("Manevra Süresi (saat)", min_value=1.0, value=4.0, step=1.0, key="fa_maneuver_duration")
    main_engine_mcr_input = st.sidebar.number_input("Ana Makine MCR (kW)", min_value=1000, value=7200, step=100, key="fa_main_engine_mcr")
    conv_aux_dg_mcr_input = st.sidebar.number_input( "Yardımcı DG MCR Değeri (kW) (Geleneksel Manevra İçin)", min_value=100, value=800, step=50, key="fa_conv_aux_dg_mcr" )
    aux_power_demand_input = st.sidebar.number_input("Yardımcı Güç İhtiyacı (kW)", min_value=0, value=300, step=50, key="fa_aux_power")

    # --- Session State Başlatma (Sadece bu sayfa için) ---
    if "fa_results_df" not in st.session_state: st.session_state.fa_results_df = pd.DataFrame()
    if "fa_detailed_df" not in st.session_state: st.session_state.fa_detailed_df = pd.DataFrame()
    if "fa_usage_df" not in st.session_state: st.session_state.fa_usage_df = pd.DataFrame()
    if "fa_show_fuel_results" not in st.session_state: st.session_state.fa_show_fuel_results = False

    @st.cache_data
    def calculate_all_results_for_fuel_analysis(
        current_gen_power_range, current_sea_power_range, current_maneuver_power_range,
        current_sea_duration, current_maneuver_duration, current_main_engine_mcr,
        current_aux_power_demand_kw, # Hem seyir hem manevra için ortak yardımcı güç
        current_conv_aux_dg_mcr_kw # Geleneksel manevra için yardımcı DG MCR'ı
    ):
        # DEĞİŞİKLİK: sfoc_data_global kullanımı kaldırıldı.
        results_summary_list = []
        detailed_data_list = []
        generator_usage_data_list = []

        # --- 1. Ana Makine Referans Verileri ---
        # Seyir Modu - Ana Makine
        total_sea_fuel_main_engine_overall = 0
        for shaft_power_sea in range(current_sea_power_range[0], current_sea_power_range[1] + 100, 100):
            if shaft_power_sea <= 0 or current_main_engine_mcr <= 0: continue
            main_engine_load_sea = (shaft_power_sea / current_main_engine_mcr) * 100
            if main_engine_load_sea > 0:
                # DEĞİŞİKLİK: Ana makine için doğru SFOC verisi kullanılıyor.
                fuel_main_ref_sea = calculate_fuel(shaft_power_sea, main_engine_load_sea, current_sea_duration, SFOC_DATA_MAIN_ENGINE)
                if fuel_main_ref_sea > 0:
                    total_sea_fuel_main_engine_overall += fuel_main_ref_sea
                    detailed_data_list.append({
                        "Combo": "Ana Makine Referans", "Mode": "Seyir", "Shaft Power (kW)": shaft_power_sea,
                        "DE Power (kW)": np.nan, "Fuel (ton)": round(fuel_main_ref_sea, 3), "System Type": "Ana Makine",
                        "Load (%)": round(main_engine_load_sea, 2)
                    })

        # Manevra Modu - Ana Makine (GÜNCELLENMİŞ HESAPLAMA: ME + Yardımcı DG'ler)
        total_maneuver_fuel_main_engine_overall = 0
        SABIT_YARDIMCI_DG_SAYISI_MANEVRA = 2
        for shaft_power_maneuver in range(current_maneuver_power_range[0], current_maneuver_power_range[1] + 100, 100):
            current_shaft_power_man = max(0, shaft_power_maneuver)

            me_propulsion_fuel_maneuver = 0
            main_engine_load_maneuver = 0
            if current_main_engine_mcr > 0:
                 main_engine_load_maneuver = (current_shaft_power_man / current_main_engine_mcr) * 100
                 if main_engine_load_maneuver >= 0:
                    # DEĞİŞİKLİK: Ana makine için doğru SFOC verisi kullanılıyor.
                    me_propulsion_fuel_maneuver = calculate_fuel(current_shaft_power_man, main_engine_load_maneuver, current_maneuver_duration, SFOC_DATA_MAIN_ENGINE)
                    me_propulsion_fuel_maneuver = me_propulsion_fuel_maneuver if me_propulsion_fuel_maneuver > 0 else 0
            
            total_aux_dg_fuel_maneuver = 0
            load_per_aux_dg_percent = 0
            if current_aux_power_demand_kw > 0 and current_conv_aux_dg_mcr_kw > 0 and SABIT_YARDIMCI_DG_SAYISI_MANEVRA > 0:
                power_per_aux_dg = current_aux_power_demand_kw / SABIT_YARDIMCI_DG_SAYISI_MANEVRA
                if power_per_aux_dg <= current_conv_aux_dg_mcr_kw:
                    load_per_aux_dg_percent = (power_per_aux_dg / current_conv_aux_dg_mcr_kw) * 100
                    if load_per_aux_dg_percent >= 0:
                        # DEĞİŞİKLİK: Yardımcı jeneratör için doğru SFOC verisi kullanılıyor.
                        fuel_one_dg = calculate_fuel(power_per_aux_dg, load_per_aux_dg_percent, current_maneuver_duration, SFOC_DATA_AUX_DG)
                        if fuel_one_dg > 0:
                            total_aux_dg_fuel_maneuver = fuel_one_dg * SABIT_YARDIMCI_DG_SAYISI_MANEVRA
                            
            total_conventional_maneuver_fuel_point = me_propulsion_fuel_maneuver + total_aux_dg_fuel_maneuver

            if total_conventional_maneuver_fuel_point > 0:
                total_maneuver_fuel_main_engine_overall += total_conventional_maneuver_fuel_point
                detailed_data_list.append({
                    "Combo": "Ana Makine Referans", "Mode": "Manevra", "Shaft Power (kW)": current_shaft_power_man,
                    "DE Power (kW)": np.nan, 
                    "Fuel (ton)": round(total_conventional_maneuver_fuel_point, 3), "System Type": "Ana Makine",
                    "Load (%)": round(main_engine_load_maneuver, 2)
                })

        # --- 2. Jeneratör Verilerini Hesapla (DE Sistemi) ---
        propulsion_path_inv_efficiency = 0.95 / (0.97*0.985*0.995*0.98)
        AUX_PATH_EFFICIENCY_FOR_DE_SEA_AUX = 0.968

        for gen_power_unit in range(current_gen_power_range[0], current_gen_power_range[1] + 100, 100):
            if gen_power_unit <= 0: continue
            combo_label = f"3 x {gen_power_unit} kW Jeneratör"
            current_combo_total_sea_fuel_generators = 0
            current_combo_total_maneuver_fuel_generators = 0

            # Seyir modu - Jeneratörler
            for shaft_power_from_slider_sea in range(current_sea_power_range[0], current_sea_power_range[1] + 100, 100):
                current_shaft_power_sea = max(0, shaft_power_from_slider_sea)
                effective_shaft_power_for_propulsion_sea = max(0, current_shaft_power_sea - current_aux_power_demand_kw)
                de_power_for_propulsion_sea = effective_shaft_power_for_propulsion_sea * propulsion_path_inv_efficiency
                de_power_for_auxiliary_sea = 0
                if current_aux_power_demand_kw > 0:
                    if AUX_PATH_EFFICIENCY_FOR_DE_SEA_AUX > 0:
                        de_power_for_auxiliary_sea = current_aux_power_demand_kw / AUX_PATH_EFFICIENCY_FOR_DE_SEA_AUX
                    else:
                        de_power_for_auxiliary_sea = float('inf')
                total_de_power_on_generators_sea = de_power_for_propulsion_sea + de_power_for_auxiliary_sea

                if total_de_power_on_generators_sea <= 0 or not np.isfinite(total_de_power_on_generators_sea):
                    continue

                ngen_sea, load_sea = determine_generator_usage(total_de_power_on_generators_sea, gen_power_unit)
                if ngen_sea is not None and load_sea is not None:
                    # DEĞİŞİKLİK: Dizel Elektrik ana jeneratörleri için doğru SFOC verisi kullanılıyor.
                    fuel_gen_sea = calculate_fuel(total_de_power_on_generators_sea, load_sea, current_sea_duration, SFOC_DATA_MAIN_DE_GEN)
                    if fuel_gen_sea > 0:
                        current_combo_total_sea_fuel_generators += fuel_gen_sea
                        detailed_data_list.append({
                            "Combo": combo_label, "Mode": "Seyir", "Shaft Power (kW)": current_shaft_power_sea,
                            "DE Power (kW)": round(total_de_power_on_generators_sea),
                            "Fuel (ton)": round(fuel_gen_sea, 3), "System Type": "Jeneratör",
                            "Load (%)": round(load_sea, 2)
                        })
                        generator_usage_data_list.append({
                            "Combo": combo_label, "Mode": "Seyir", "DE Power (kW)": round(total_de_power_on_generators_sea),
                            "Generators Used": ngen_sea, "Load Per Generator (%)": round(load_sea, 2)
                        })

            # Manevra modu - Jeneratörler
            for shaft_power_from_slider_maneuver in range(current_maneuver_power_range[0], current_maneuver_power_range[1] + 100, 100):
                current_shaft_power_man = max(0, shaft_power_from_slider_maneuver)
                de_power_for_propulsion_man = current_shaft_power_man * propulsion_path_inv_efficiency
                de_power_for_auxiliary_man = current_aux_power_demand_kw if current_aux_power_demand_kw > 0 else 0
                total_de_power_on_generators_man = de_power_for_propulsion_man + de_power_for_auxiliary_man

                if total_de_power_on_generators_man <= 0 or not np.isfinite(total_de_power_on_generators_man):
                    continue
                
                ngen_maneuver, load_maneuver = determine_generator_usage(total_de_power_on_generators_man, gen_power_unit)
                if ngen_maneuver is not None and load_maneuver is not None:
                    # DEĞİŞİKLİK: Dizel Elektrik ana jeneratörleri için doğru SFOC verisi kullanılıyor.
                    fuel_gen_maneuver = calculate_fuel(total_de_power_on_generators_man, load_maneuver, current_maneuver_duration, SFOC_DATA_MAIN_DE_GEN)
                    if fuel_gen_maneuver > 0:
                        current_combo_total_maneuver_fuel_generators += fuel_gen_maneuver
                        detailed_data_list.append({
                            "Combo": combo_label, "Mode": "Manevra", "Shaft Power (kW)": current_shaft_power_man,
                            "DE Power (kW)": round(total_de_power_on_generators_man),
                            "Fuel (ton)": round(fuel_gen_maneuver, 3), "System Type": "Jeneratör",
                            "Load (%)": round(load_maneuver, 2)
                        })
                        generator_usage_data_list.append({
                            "Combo": combo_label, "Mode": "Manevra", "DE Power (kW)": round(total_de_power_on_generators_man),
                            "Generators Used": ngen_maneuver, "Load Per Generator (%)": round(load_maneuver, 2)
                        })
            
            if current_combo_total_sea_fuel_generators > 0 or current_combo_total_maneuver_fuel_generators > 0:
                sea_diff = total_sea_fuel_main_engine_overall - current_combo_total_sea_fuel_generators
                canal_passage_diff = total_maneuver_fuel_main_engine_overall - current_combo_total_maneuver_fuel_generators
                berthing_maneuver_diff = total_maneuver_fuel_main_engine_overall - (current_combo_total_maneuver_fuel_generators/8)
                results_summary_list.append({
                    "Jeneratör Kombinasyonu": combo_label,
                    "Seyirde Yakılan Yakıt (DE) (ton)": round(current_combo_total_sea_fuel_generators, 2),
                    "Manevrada Yakılan Yakıt (DE) (ton)": round(current_combo_total_maneuver_fuel_generators, 2),
                    "Seyir Yakıt Farkı (ton)": round(sea_diff, 2),
                    "Kanal Geçiş Yakıt Farkı (ton)": round(canal_passage_diff, 2),
                    "Yanaşma Manevrası Yakıt Farkı (ton)": round(berthing_maneuver_diff, 2)
                })
        
        return pd.DataFrame(results_summary_list), pd.DataFrame(detailed_data_list), pd.DataFrame(generator_usage_data_list)

    # ... Kodun geri kalanı orijinal haliyle korunuyor ...
    # "HESAPLA" butonu ve sonrası olduğu gibi kalır.
    if st.sidebar.button("HESAPLA", key="fa_calculate_button"):
        st.session_state.fa_show_fuel_results = True
        st.session_state.fa_results_df, st.session_state.fa_detailed_df, st.session_state.fa_usage_df = \
            calculate_all_results_for_fuel_analysis(
                gen_power_range_input, sea_power_range_input, maneuver_power_range_input,
                sea_duration_input, maneuver_duration_input, main_engine_mcr_input,
                aux_power_demand_input,
                conv_aux_dg_mcr_input
            )
        if st.session_state.fa_results_df.empty and st.session_state.fa_detailed_df.empty:
             st.warning("Hesaplama yapıldı ancak 'Yakıt Analizi' için gösterilecek sonuç bulunamadı. Girdilerinizi kontrol edin.")

    st.header("Jeneratör ve Ana Makine Yakıt Tüketim Analizi")

    if st.session_state.fa_show_fuel_results and not st.session_state.fa_results_df.empty:
        st.subheader("Özet Sonuçlar")
        st.dataframe(st.session_state.fa_results_df, use_container_width=True)

        st.markdown("---")
        st.subheader("Detaylı Grafiksel Analiz")

        # Karşılaştırma için uygun jeneratör kombinasyonlarını bul
        available_gen_combos_fa = []
        if not st.session_state.fa_detailed_df.empty:
            available_gen_combos_fa = [
                combo for combo in st.session_state.fa_detailed_df["Combo"].unique()
                if combo != "Ana Makine Referans"
            ]

        if available_gen_combos_fa:
            selected_gen_combo_fa = st.selectbox(
                "Karşılaştırılacak Jeneratör Kombinasyonunu Seçin",
                available_gen_combos_fa, key="fa_select_gen_combo_plot"
            )
            plot_mode_fa = st.radio(
                "Analiz Modunu Seçin", ["Seyir", "Manevra"],
                horizontal=True, key="fa_plot_mode_radio"
            )

            # Karşılaştırma grafiği için veri filtreleme
            plot_data_gen_selected_fa = st.session_state.fa_detailed_df[
                (st.session_state.fa_detailed_df["Combo"] == selected_gen_combo_fa) &
                (st.session_state.fa_detailed_df["System Type"] == "Jeneratör") &
                (st.session_state.fa_detailed_df["Mode"] == plot_mode_fa) &
                (st.session_state.fa_detailed_df["Fuel (ton)"].notna()) &
                (st.session_state.fa_detailed_df["Fuel (ton)"] > 0) # Sadece pozitif yakıt değerleri
            ]
            plot_data_me_ref_fa = st.session_state.fa_detailed_df[
                (st.session_state.fa_detailed_df["System Type"] == "Ana Makine") &
                (st.session_state.fa_detailed_df["Mode"] == plot_mode_fa) &
                (st.session_state.fa_detailed_df["Fuel (ton)"].notna()) &
                (st.session_state.fa_detailed_df["Fuel (ton)"] > 0)
            ]
            combined_fuel_plot_data_fa = pd.concat([plot_data_gen_selected_fa, plot_data_me_ref_fa]).reset_index(drop=True)

            if not combined_fuel_plot_data_fa.empty:
                fig_fuel_comparison_fa = px.bar(
                    combined_fuel_plot_data_fa,
                    x="Shaft Power (kW)", y="Fuel (ton)", color="System Type",
                    barmode="group",
                    title=f"{selected_gen_combo_fa} vs Ana Makine Referans ({plot_mode_fa} Modu)",
                    labels={"Fuel (ton)": "Yakıt (ton)", "Shaft Power (kW)": "Şaft Gücü (kW)", "System Type": "Sistem Tipi"}
                )
                st.plotly_chart(fig_fuel_comparison_fa, use_container_width=True)
            else:
                st.warning(f"{plot_mode_fa} modu için {selected_gen_combo_fa} veya Ana Makine Referansına ait gösterilecek karşılaştırmalı yakıt verisi bulunamadı.")

            # Jeneratör Kullanım Grafiği (Sadece seçilen jeneratör kombinasyonu için)
            gen_usage_plot_data_fa = st.session_state.fa_usage_df[
                (st.session_state.fa_usage_df["Combo"] == selected_gen_combo_fa) &
                (st.session_state.fa_usage_df["Mode"] == plot_mode_fa)
            ]
            if not gen_usage_plot_data_fa.empty:
                fig_usage_fa = px.bar(
                    gen_usage_plot_data_fa,
                    x="DE Power (kW)", y="Generators Used",
                    hover_data=["Load Per Generator (%)"],
                    barmode="group",
                    title=f"{selected_gen_combo_fa} - Jeneratör Kullanımı ({plot_mode_fa} Modu)",
                    labels={"Generators Used": "Kullanılan Jeneratör Sayısı", "DE Power (kW)": "Dizel Elektrik Gücü (kW)"}
                )
                fig_usage_fa.update_traces(
                    text=gen_usage_plot_data_fa["Load Per Generator (%)"].apply(lambda x: f'{x:.2f}%'),
                    textposition='outside'
                )
                st.plotly_chart(fig_usage_fa, use_container_width=True)

        elif not st.session_state.fa_detailed_df.empty: # Detaylı veri var ama jeneratör kombosu yok (sadece ana makine olabilir)
            st.info("Hesaplama sonucunda jeneratör kombinasyonu bulunamadı, sadece Ana Makine Referans verileri mevcut olabilir.")
            # İsteğe bağlı: Sadece ana makine verilerini gösteren bir grafik eklenebilir.
            plot_data_me_ref_only_fa = st.session_state.fa_detailed_df[
                (st.session_state.fa_detailed_df["System Type"] == "Ana Makine") &
                (st.session_state.fa_detailed_df["Fuel (ton)"].notna()) &
                (st.session_state.fa_detailed_df["Fuel (ton)"] > 0)
            ]
            if not plot_data_me_ref_only_fa.empty:
                plot_mode_me_only_fa = st.radio(
                    "Ana Makine Analiz Modunu Seçin", ["Seyir", "Manevra"],
                    horizontal=True, key="fa_plot_mode_me_only_selector"
                )
                plot_data_me_ref_only_filtered_fa = plot_data_me_ref_only_fa[plot_data_me_ref_only_fa["Mode"] == plot_mode_me_only_fa]
                if not plot_data_me_ref_only_filtered_fa.empty:
                    fig_fuel_me_only_fa = px.bar(
                        plot_data_me_ref_only_filtered_fa,
                        x="Shaft Power (kW)", y="Fuel (ton)", color="Mode",
                        title=f"Ana Makine Referans Yakıt Tüketimi ({plot_mode_me_only_fa})",
                        labels={"Fuel (ton)": "Yakıt (ton)", "Shaft Power (kW)": "Şaft Gücü (kW)"}
                    )
                    st.plotly_chart(fig_fuel_me_only_fa, use_container_width=True)

    elif st.session_state.fa_show_fuel_results and st.session_state.fa_results_df.empty:
        # Bu kontrol, HESAPLA butonuna basıldıktan sonra boş DataFrame'ler döndüğünde çalışır.
        st.warning("Girilen parametrelerle 'Yakıt Analizi' için hesaplanacak uygun bir senaryo bulunamadı.")

    # --- SFOC - Yük Eğrisi Grafiği (Kullanıcı Seçimli) ---
    st.markdown("---")
    st.subheader("Özgül Yakıt Tüketimi (SFOC) - Yük Eğrisi")

    # Kullanıcının makine tipi seçmesi için bir selectbox oluştur
    # ALL_SFOC_CURVES sözlüğünü config.py'den import ettiğinizden emin olun.
    # (Bu importun dosyanın başında yapıldığını varsayıyorum)

    sfoc_option_labels = {
        "main_engine": "Ana Makine (Geleneksel)",
        "main_de_gen": "Ana Dizel Jeneratör (DE)",
        "port_gen": "Liman Jeneratörü (DE)",
        "aux_dg": "Yardımcı Dizel Jeneratör (Geleneksel)"
    }
    # ALL_SFOC_CURVES anahtarlarının sfoc_option_labels'da olduğundan emin olalım
    display_options = [sfoc_option_labels.get(key, key.replace("_", " ").title()) for key in ALL_SFOC_CURVES.keys()]
    
    # Seçilen etiketi tekrar anahtara çevirmek için ters bir eşleme
    # Bu eşlemenin sadece sfoc_option_labels'da tanımlı anahtarlar için doğru çalışacağına dikkat edin.
    key_map = {label: key for key, label in sfoc_option_labels.items()}

    selected_sfoc_label = st.selectbox(
        "SFOC Eğrisini Görmek İstediğiniz Makine Tipini Seçin:",
        options=display_options,
        key="fa_sfoc_curve_selector" 
    )

    # Seçilen etikete karşılık gelen SFOC veri anahtarını al
    # Eğer etiket sfoc_option_labels'da yoksa, etiketi doğrudan anahtar olarak kullanmayı dene (bu pek olası değil)
    selected_sfoc_key = key_map.get(selected_sfoc_label, selected_sfoc_label.lower().replace(" ", "_"))


    if selected_sfoc_key and selected_sfoc_key in ALL_SFOC_CURVES:
        sfoc_data_to_plot = ALL_SFOC_CURVES[selected_sfoc_key]

        if sfoc_data_to_plot and isinstance(sfoc_data_to_plot, dict) and len(sfoc_data_to_plot) >= 2:
            loads_original = list(sfoc_data_to_plot.keys())
            sfocs_original = list(sfoc_data_to_plot.values())
            
            sorted_indices = np.argsort(loads_original)
            sorted_loads_original = np.array(loads_original)[sorted_indices]
            sorted_sfocs_original = np.array(sfocs_original)[sorted_indices]

            df_sfoc_points = pd.DataFrame({'Yük (%)': sorted_loads_original, 'SFOC (g/kWh)': sorted_sfocs_original})
            
            plot_min_load, plot_max_load = 0, 110 
            interpolated_loads = np.linspace(plot_min_load, plot_max_load, 200)
            
            interpolated_sfocs = [interpolate_sfoc_non_linear(load, sfoc_data_to_plot) for load in interpolated_loads]

            valid_interpolated_data = [(load, sfoc) for load, sfoc in zip(interpolated_loads, interpolated_sfocs) if sfoc is not None and sfoc >= 50]
            
            if valid_interpolated_data:
                interpolated_loads_valid, interpolated_sfocs_valid = zip(*valid_interpolated_data)
                df_sfoc_curve = pd.DataFrame({'Yük (%)': interpolated_loads_valid, 'SFOC (g/kWh)': interpolated_sfocs_valid})

                fig_sfoc_display = px.line(df_sfoc_curve, x='Yük (%)', y='SFOC (g/kWh)',
                                         title=f'{selected_sfoc_label} - SFOC vs. Yük Yüzdesi (İnterpolasyonlu)',
                                         labels={'Yük (%)': 'Jeneratör Yükü (%)', 'SFOC (g/kWh)': 'SFOC (g/kWh)'})
                fig_sfoc_display.add_scatter(x=df_sfoc_points['Yük (%)'], y=df_sfoc_points['SFOC (g/kWh)'],
                                           mode='markers', name='Orjinal Veri Noktaları',
                                           marker=dict(color='red', size=10, symbol='circle'))
                
                min_y_display = max(0, df_sfoc_points['SFOC (g/kWh)'].min() - 10) if not df_sfoc_points.empty else 150
                max_y_display = df_sfoc_points['SFOC (g/kWh)'].max() + 10 if not df_sfoc_points.empty else 250
                fig_sfoc_display.update_yaxes(range=[min_y_display, max_y_display])
                fig_sfoc_display.update_xaxes(range=[plot_min_load - 5, plot_max_load + 5])
                st.plotly_chart(fig_sfoc_display, use_container_width=True)
            else:
                st.warning(f"{selected_sfoc_label} için SFOC eğrisi çizilemedi. İnterpolasyon için yeterli veya geçerli veri bulunamadı.")
        else:
            st.warning(f"{selected_sfoc_label} için SFOC verisi bulunamadı veya geçersiz. Lütfen config.py dosyasını kontrol edin.")
    else:
        st.error(f"'{selected_sfoc_label}' için SFOC anahtarı bulunamadı veya geçersiz.")

    # --- Güç Akışı ve Kayıplar Diyagramı ---
    st.markdown("---")
    st.subheader("Dizel Elektrik Güç Akışı ve Kayıpları Diyagramı")
    st.sidebar.header("Güç Akışı Diyagramı Ayarları") # Ayrı başlık altında
    if "fa_diagram_shaft_power" not in st.session_state: st.session_state.fa_diagram_shaft_power = 3000 # Default

    diagram_shaft_power_input = st.sidebar.number_input(
        "Diyagram için Şaft Gücü (kW)", min_value=100,
        value=int(st.session_state.fa_diagram_shaft_power), step=50, key="fa_diag_shaft_power_widget"
    )
    st.sidebar.subheader("Sistem Verimlilikleri (%) (Diyagram İçin)")
    motor_eff_diag_perc = st.sidebar.slider("Diyagram - Elektrik Motoru Verimliliği (%)", 90.0, 99.9, 97.0, step=0.1, key="fa_diag_motor_eff")
    converter_eff_diag_perc = st.sidebar.slider("Diyagram - Frekans Konvertörü Verimliliği (%)", 90.0, 99.9, 98.5, step=0.1, key="fa_diag_converter_eff")
    switchboard_eff_diag_perc = st.sidebar.slider("Diyagram - Pano Verimliliği (%)", 90.0, 99.9, 99.8, step=0.1, key="fa_diag_switchboard_eff")
    generator_alt_eff_diag_perc = st.sidebar.slider("Diyagram - Alternatör Elektriksel Verimliliği (%)", 90.0, 99.9, 97.0, step=0.1, key="fa_diag_gen_alt_eff")

    # Hesaplama için verimlilikleri 0-1 aralığına çevir
    motor_eff_d = motor_eff_diag_perc / 100.0
    converter_eff_d = converter_eff_diag_perc / 100.0
    switchboard_eff_d = switchboard_eff_diag_perc / 100.0 # Pano geçiş verimliliği
    generator_alt_eff_d = generator_alt_eff_diag_perc / 100.0 # Alternatörün kendi verimliliği

    power_vals, loss_vals = calculate_power_flow(
        diagram_shaft_power_input, motor_eff_d, converter_eff_d, switchboard_eff_d, generator_alt_eff_d
    )

    if power_vals and loss_vals: # Bu satırla başlayan blok
        dot = graphviz.Digraph('power_flow_diagram', comment='Güç Akışı ve Kayıplar (İyileştirilmiş Stil)')
        dot.attr(rankdir='LR')
        dot.attr('node', shape='plaintext', fontsize='14', fontname='Arial') # shape='plaintext' HTML etiketleri için
        dot.attr('edge', fontsize='12', fontname='Arial')

        # format_loss_perc_diag fonksiyonunun bu if bloğundan önce tanımlandığından emin olun,
        # veya bu blok içine taşıyın eğer sadece burada kullanılıyorsa.
        # Önceki cevabımda bu fonksiyonun tanımı Graphviz bloğunun dışındaydı, o daha iyi.
        # Eğer format_loss_perc_diag zaten yukarıda tanımlıysa, tekrar tanımlamanıza gerek yok.
        # Sadece emin olmak için:
        def format_loss_perc_diag(percent_val):
             return f'({percent_val:.1f}%)' if not np.isnan(percent_val) else '(N/A)'


        with dot.subgraph(name='cluster_electrical') as c:
            c.attr(style='rounded', color='#EEEEEE', label='Elektriksel Sistem') # Gri arka planlı küme

            # Alternatör Düğümü
            c.node('alternator_in', label=f"""<
<TABLE BORDER='0' CELLBORDER='1' CELLSPACING='0' CELLPADDING='5' BGCOLOR='#E0F2F7'>
    <TR><TD COLSPAN='2' ALIGN='CENTER'><B>Alternatörler</B></TD></TR>
    <TR><TD ALIGN='LEFT'>Mekanik Giriş:</TD><TD ALIGN='RIGHT'>{power_vals['alternator_mech_input']:.0f} kW</TD></TR>
    <TR><TD ALIGN='LEFT'>Elektrik Çıkış:</TD><TD ALIGN='RIGHT'>{power_vals['alternator_elec_output']:.0f} kW</TD></TR>
    <TR><TD ALIGN='LEFT' BGCOLOR='#FFEBEE'><FONT COLOR='#B71C1C'>Kayıp:</FONT></TD><TD ALIGN='RIGHT' BGCOLOR='#FFEBEE'><FONT COLOR='#B71C1C'>{loss_vals['alternator']:.0f} kW ({format_loss_perc_diag((1-generator_alt_eff_d)*100)})</FONT></TD></TR>
</TABLE>>""", tooltip="Alternatörler ve verimliliği")

            # Ana Pano Düğümü
            c.node('switchboard', label=f"""<
<TABLE BORDER='0' CELLBORDER='1' CELLSPACING='0' CELLPADDING='5' BGCOLOR='#F0F4C3'>
    <TR><TD ALIGN='CENTER'><B>Ana Pano</B></TD></TR>
    <TR><TD ALIGN='LEFT'>Giriş:</TD><TD ALIGN='RIGHT'>{power_vals['switchboard_input_from_gens']:.0f} kW</TD></TR>
    <TR><TD ALIGN='LEFT' BGCOLOR='#FFEBEE'><FONT COLOR='#B71C1C'>Kayıp:</FONT></TD><TD ALIGN='RIGHT' BGCOLOR='#FFEBEE'><FONT COLOR='#B71C1C'>{loss_vals['switchboard']:.0f} kW ({format_loss_perc_diag((1-switchboard_eff_d)*100)})</FONT></TD></TR>
</TABLE>>""", tooltip="Ana Pano ve kayıpları")

            # Frekans Konvertörü Düğümü
            c.node('converter', label=f"""<
<TABLE BORDER='0' CELLBORDER='1' CELLSPACING='0' CELLPADDING='5' BGCOLOR='#FCE4EC'>
    <TR><TD ALIGN='CENTER'><B>Frekans Konvertörü</B></TD></TR>
    <TR><TD ALIGN='LEFT'>Giriş:</TD><TD ALIGN='RIGHT'>{power_vals['converter_input']:.0f} kW</TD></TR>
    <TR><TD ALIGN='LEFT' BGCOLOR='#FFEBEE'><FONT COLOR='#B71C1C'>Kayıp:</FONT></TD><TD ALIGN='RIGHT' BGCOLOR='#FFEBEE'><FONT COLOR='#B71C1C'>{loss_vals['converter']:.0f} kW ({format_loss_perc_diag((1-converter_eff_d)*100)})</FONT></TD></TR>
</TABLE>>""", tooltip="Frekans Konvertörü ve kayıpları")

        # Elektrik Motoru Düğümü (Küme dışında olabilir veya içinde)
        dot.node('motor_out', label=f"""<
<TABLE BORDER='0' CELLBORDER='1' CELLSPACING='0' CELLPADDING='5' BGCOLOR='#D4EDDA'>
    <TR><TD ALIGN='CENTER'><B>Elektrik Motoru</B></TD></TR>
    <TR><TD ALIGN='LEFT'>Giriş:</TD><TD ALIGN='RIGHT'>{power_vals['motor_input']:.0f} kW</TD></TR>
    <TR><TD ALIGN='LEFT'>Çıkış (Şafta):</TD><TD ALIGN='RIGHT'>{power_vals['shaft']:.0f} kW</TD></TR>
    <TR><TD ALIGN='LEFT' BGCOLOR='#FFEBEE'><FONT COLOR='#B71C1C'>Kayıp:</FONT></TD><TD ALIGN='RIGHT' BGCOLOR='#FFEBEE'><FONT COLOR='#B71C1C'>{loss_vals['motor']:.0f} kW ({format_loss_perc_diag((1-motor_eff_d)*100)})</FONT></TD></TR>
</TABLE>>""", tooltip="Elektrik Motoru ve kayıpları")
        
        # Ana Tahrik Elemanı (Sanal Düğüm) - Daha yukarıda, akışın başında olabilir
        dot.node('prime_mover', label=f"""<
<TABLE BORDER='0' CELLBORDER='1' CELLSPACING='0' CELLPADDING='5' BGCOLOR='#FFF9C4'>
    <TR><TD ALIGN='CENTER'><B>Ana Tahrik Elemanı</B><BR/>(Dizel Motorlar)</TD></TR>
</TABLE>>""", tooltip="Yakıtın enerjiye dönüştüğü yer")

        # Şaft Gücü Düğümü
        dot.node('shaft_node', label=f"""<
<TABLE BORDER='0' CELLBORDER='1' CELLSPACING='0' CELLPADDING='5' BGCOLOR='#E1BEE7'>
    <TR><TD ALIGN='CENTER'><B>Şaft Gücü (Pervane)</B></TD></TR>
    <TR><TD ALIGN='CENTER'>{power_vals['shaft']:.0f} kW</TD></TR>
</TABLE>>""", tooltip="Pervaneye iletilen net güç")


        # Kenarlar (Güç Akışı) - Renkler ve oklar
        dot.edge('prime_mover', 'alternator_in', label=f"Mekanik Güç\n{power_vals['alternator_mech_input']:.0f} kW", penwidth="2", color="#4A148C", style="dashed", arrowhead="normal", fontcolor="#4A148C")
        dot.edge('alternator_in', 'switchboard', label=f"{power_vals['alternator_elec_output']:.0f} kW", penwidth="2.5", color="#1B5E20", arrowhead="vee", fontcolor="#1B5E20")
        dot.edge('switchboard', 'converter', label=f"{power_vals['converter_input']:.0f} kW", penwidth="2.5", color="#E65100", arrowhead="vee", fontcolor="#E65100")
        dot.edge('converter', 'motor_out', label=f"{power_vals['motor_input']:.0f} kW", penwidth="2.5", color="#AD1457", arrowhead="vee", fontcolor="#AD1457")
        dot.edge('motor_out', 'shaft_node', label=f"{power_vals['shaft']:.0f} kW", penwidth="2.5", color="#0D47A1", arrowhead="vee", fontcolor="#0D47A1")

        st.markdown("### Güç Akışı ve Kayıplar")
        st.graphviz_chart(dot, use_container_width=True) # use_container_width=True daha iyi olabilir
    # ^^^ BİR ÖNCEKİ CEVAPTAKİ İYİLEŞTİRİLMİŞ KOD BURADA BİTER ^^^

    # Bu satırlar (st.info ve sonrası) yeni Graphviz bloğundan sonra gelmeli:
        total_system_loss = loss_vals["motor"] + loss_vals["converter"] + loss_vals["switchboard"] + loss_vals["alternator"]
        st.info(f"Girilen Şaft Gücü ({power_vals['shaft']:.0f} kW) için Alternatörlere gereken Toplam Mekanik Güç: {power_vals['alternator_mech_input']:.0f} kW. \n"
            f"Toplam Sistem Kaybı (Alternatör, Pano, Konvertör, Motor): {total_system_loss:.0f} kW.")
        
    elif diagram_shaft_power_input > 0:
        st.warning("Güç Akışı diyagramı hesaplanamadı. Lütfen Diyagram için Şaft Gücü'nün pozitif ve tüm sistem verimliliklerinin %0'dan büyük olduğundan emin olun.")
    else:
        st.info("Güç Akışı diyagramını görmek için lütfen sidebar'dan 'Diyagram için Şaft Gücü' değeri girin ve verimlilikleri ayarlayın.")
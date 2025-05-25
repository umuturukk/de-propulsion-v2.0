# new_combinations_page.py
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# Proje içi modüllerden importlar
# DEĞİŞİKLİK: İlgili SFOC verileri ve ALL_SFOC_CURVES import ediliyor
from config import (
    CONVENTIONAL_SHAFT_EFFICIENCY,
    PROPULSION_PATH_INV_EFFICIENCY,
    SFOC_DATA_MAIN_ENGINE,
    SFOC_DATA_AUX_DG,
    ALL_SFOC_CURVES
)
from core_calculations import (
    calculate_fuel,
    get_best_combination
)

def render_page():
    """ "Yeni Jeneratör Kombinasyonları" sayfasının içeriğini ve mantığını render eder. """
    st.header("Yeni Jeneratör Kombinasyonları Analizi")

    st.sidebar.header("Yeni Kombinasyon Girdi Ayarları")
    # Widget'lar orijinal haliyle korunuyor
    main_gen_mcr_new = st.sidebar.number_input("Ana Jeneratör MCR (kW)", min_value=100, value=2400, step=100, key="nc_main_gen_mcr")
    main_gen_qty_new = st.sidebar.number_input("Ana Jeneratör Adedi", min_value=1, value=3, step=1, key="nc_main_gen_qty")
    port_gen_mcr_new = st.sidebar.number_input("Liman Jeneratörü MCR (kW)", min_value=50, value=1000, step=50, key="nc_port_gen_mcr")
    port_gen_qty_new = st.sidebar.number_input("Liman Jeneratörü Adedi", min_value=0, value=1, step=1, key="nc_port_gen_qty")

    sea_power_range_new = st.sidebar.slider("Seyir Şaft Güç Aralığı (kW)", 2500, 5500, (3000, 4400), step=100, key="nc_sea_power_range")
    maneuver_power_range_new = st.sidebar.slider("Manevra Şaft Güç Aralığı (kW)", 1500, 3500, (1600, 2700), step=100, key="nc_maneuver_power_range")
    sea_duration_new = st.sidebar.number_input("Seyir Süresi (saat)", min_value=1.0, value=48.0, step=1.0, key="nc_sea_duration")
    maneuver_duration_new = st.sidebar.number_input("Manevra Süresi (saat)", min_value=1.0, value=4.0, step=1.0, key="nc_maneuver_duration")
    main_engine_mcr_ref_new = st.sidebar.number_input("Ana Makine MCR (kW) (Referans İçin)", min_value=1000, value=7200, step=100, key="nc_main_engine_mcr_ref")
    nc_conv_aux_dg_mcr_input = st.sidebar.number_input(
        "Yardımcı DG MCR Değeri (kW) (Ref. Manevra İçin)",
        min_value=100, value=800, step=50, key="nc_conv_aux_dg_mcr"
    )
    nc_aux_power_demand_input = st.sidebar.number_input(
        "Yardımcı Güç İhtiyacı (kW) (Seyir/Manevra)",
        min_value=0, value=300, step=50, key="nc_aux_power"
    )

    st.sidebar.subheader("Sistem Verimlilikleri (%) (Yeni Kombinasyon İçin)")
    motor_eff_new_perc = st.sidebar.slider("Yeni - Elektrik Motoru Verimliliği (%)", 90.0, 99.9, 97.0, step=0.1, key="nc_motor_eff_slider")
    converter_eff_new_perc = st.sidebar.slider("Yeni - Frekans Dönüştürücü Verimliliği (%)", 90.0, 99.9, 98.5, step=0.1, key="nc_converter_eff_slider")
    switchboard_eff_new_perc = st.sidebar.slider("Yeni - Main Switchboard Verimliliği (%)", 90.0, 99.9, 99.5, step=0.1, key="nc_switchboard_eff_slider")
    generator_elec_eff_new_perc = st.sidebar.slider("Yeni - Alternatör Verimliliği (%)", 90.0, 99.9, 98.0, step=0.1, key="nc_generator_elec_eff_slider")

    total_elec_eff_new_factor = (motor_eff_new_perc / 100.0) * (converter_eff_new_perc / 100.0) * (switchboard_eff_new_perc / 100.0) * (generator_elec_eff_new_perc / 100.0)

    if total_elec_eff_new_factor <= 1e-6:
        st.warning("Yeni Kombinasyon için toplam sistem verimliliği (motor*conv*pano*alt) sıfıra çok yakın veya sıfır. Lütfen verimlilikleri kontrol edin.")

    if "nc_results_df" not in st.session_state: st.session_state.nc_results_df = pd.DataFrame()
    if "nc_detailed_df" not in st.session_state: st.session_state.nc_detailed_df = pd.DataFrame()
    if "nc_usage_df" not in st.session_state: st.session_state.nc_usage_df = pd.DataFrame()
    if "nc_show_results" not in st.session_state: st.session_state.nc_show_results = False

    @st.cache_data
    def calculate_all_results_for_new_combinations(
        p_main_gen_mcr, p_main_gen_qty, p_port_gen_mcr, p_port_gen_qty,
        p_sea_power_range, p_maneuver_power_range,
        p_sea_duration, p_maneuver_duration,
        p_main_engine_mcr_ref,
        p_total_elec_eff_factor_arg,
        p_conventional_shaft_eff_arg,
        # DEĞİŞİKLİK: p_sfoc_data argümanı kaldırıldı, artık kullanılmıyor.
        p_current_aux_power_demand_kw,
        p_current_conv_aux_dg_mcr_kw
    ):
        results_summary_list = []
        detailed_data_list = []
        generator_usage_data_list = []

        # --- 1. Ana Makine Referans Tüketimini Hesapla ---
        total_sea_fuel_main_engine_ref = 0
        for shaft_power in range(p_sea_power_range[0], p_sea_power_range[1] + 100, 100):
            if shaft_power <= 0 or p_main_engine_mcr_ref <= 0: continue
            load = (shaft_power / p_main_engine_mcr_ref) * 100
            if load > 0:
                # DEĞİŞİKLİK: Geleneksel ana makine için doğru SFOC verisi kullanılıyor.
                fuel = calculate_fuel(shaft_power, load, p_sea_duration, SFOC_DATA_MAIN_ENGINE)
                if fuel > 0:
                    total_sea_fuel_main_engine_ref += fuel
                    # Orijinal koddaki gibi listeye ekleme
                    detailed_data_list.append({
                        "Combo": "Ana Makine Referans", "SpecificComboUsed": "Ana Makine Referans", "Mode": "Seyir",
                        "Shaft Power (kW)": shaft_power, "Required DE Power (kW)": np.nan,
                        "Fuel (ton)": round(fuel, 3), "System Type": "Ana Makine",
                        "Load (%)": round(load, 2), "Gen Type": "Ana Makine", "N_running_combo": 1,
                        "OriginalMainOnlyFuel (ton)": np.nan, "OriginalMainOnlyLabel": np.nan, "IsAssisted": False
                    })
        
        total_maneuver_fuel_main_engine_ref = 0
        SABIT_YARDIMCI_DG_SAYISI_MANEVRA_REF = 2
        for shaft_power_maneuver_ref in range(p_maneuver_power_range[0], p_maneuver_power_range[1] + 100, 100):
            current_shaft_power_man_ref = max(0, shaft_power_maneuver_ref)
            me_propulsion_fuel_maneuver_ref = 0
            main_engine_load_maneuver_ref = 0
            if p_main_engine_mcr_ref > 0:
                 main_engine_load_maneuver_ref = (current_shaft_power_man_ref / p_main_engine_mcr_ref) * 100
                 # DEĞİŞİKLİK: Geleneksel ana makine için doğru SFOC verisi kullanılıyor.
                 me_propulsion_fuel_maneuver_ref = calculate_fuel(current_shaft_power_man_ref, main_engine_load_maneuver_ref, p_maneuver_duration, SFOC_DATA_MAIN_ENGINE)
                 me_propulsion_fuel_maneuver_ref = me_propulsion_fuel_maneuver_ref if me_propulsion_fuel_maneuver_ref > 0 else 0
            
            total_aux_dg_fuel_maneuver_ref = 0
            if p_current_aux_power_demand_kw > 0 and p_current_conv_aux_dg_mcr_kw > 0 and SABIT_YARDIMCI_DG_SAYISI_MANEVRA_REF > 0:
                power_per_aux_dg_ref = p_current_aux_power_demand_kw / SABIT_YARDIMCI_DG_SAYISI_MANEVRA_REF
                if power_per_aux_dg_ref <= p_current_conv_aux_dg_mcr_kw:
                    load_per_aux_dg_percent_ref = (power_per_aux_dg_ref / p_current_conv_aux_dg_mcr_kw) * 100
                    if load_per_aux_dg_percent_ref >=0:
                        # DEĞİŞİKLİK: Geleneksel yardımcı jeneratör için doğru SFOC verisi kullanılıyor.
                        fuel_one_dg_ref = calculate_fuel(power_per_aux_dg_ref, load_per_aux_dg_percent_ref, p_maneuver_duration, SFOC_DATA_AUX_DG)
                        if fuel_one_dg_ref > 0:
                            total_aux_dg_fuel_maneuver_ref = fuel_one_dg_ref * SABIT_YARDIMCI_DG_SAYISI_MANEVRA_REF
            
            total_conventional_maneuver_fuel_point_ref = me_propulsion_fuel_maneuver_ref + total_aux_dg_fuel_maneuver_ref
            if total_conventional_maneuver_fuel_point_ref > 0:
                total_maneuver_fuel_main_engine_ref += total_conventional_maneuver_fuel_point_ref
                # Orijinal koddaki gibi listeye ekleme
                detailed_data_list.append({
                    "Combo": "Ana Makine Referans", "SpecificComboUsed": "Ana Makine Referans", "Mode": "Manevra",
                    "Shaft Power (kW)": current_shaft_power_man_ref, "Required DE Power (kW)": np.nan,
                    "Fuel (ton)": round(total_conventional_maneuver_fuel_point_ref, 3), "System Type": "Ana Makine",
                    "Load (%)": round(main_engine_load_maneuver_ref, 2), "Gen Type": "Ana Makine", "N_running_combo": 1,
                    "OriginalMainOnlyFuel (ton)": np.nan, "OriginalMainOnlyLabel": np.nan, "IsAssisted": False
                })

        # --- 2. Yeni Jeneratör Konfigürasyonu için Tüketimi Hesapla ---
        # Bu bölümdeki mantık orijinal haliyle korunuyor
        current_combo_total_sea_fuel_gens = 0
        current_combo_total_maneuver_fuel_gens = 0
        gen_config_label = f"{p_main_gen_qty}x{p_main_gen_mcr}kW Ana"
        if p_port_gen_qty > 0 and p_port_gen_mcr > 0:
            gen_config_label += f" + {p_port_gen_qty}x{p_port_gen_mcr}kW Liman"
        
        for mode_params in [(p_sea_power_range, p_sea_duration, "Seyir"), (p_maneuver_power_range, p_maneuver_duration, "Manevra")]:
            power_range, duration, mode_label = mode_params
            for shaft_power_loop_input in range(power_range[0], power_range[1] + 100, 100):
                # Orijinal koddaki güç hesaplama mantığı korunuyor
                current_P_pervane_hedef = max(0, shaft_power_loop_input)
                required_de_power_for_prop = 0.0
                de_power_for_auxiliary = 0.0
                total_de_power_for_get_best_combination = 0.0

                if mode_label == "Seyir":
                    power_basis_for_de_prop_sea = current_P_pervane_hedef * p_conventional_shaft_eff_arg 
                    if p_total_elec_eff_factor_arg > 1e-9:
                        required_de_power_for_prop = power_basis_for_de_prop_sea / p_total_elec_eff_factor_arg
                    elif power_basis_for_de_prop_sea > 0:
                        required_de_power_for_prop = float('inf')
                    de_power_for_auxiliary = p_current_aux_power_demand_kw if p_current_aux_power_demand_kw > 0 else 0.0
                    total_de_power_for_get_best_combination = required_de_power_for_prop 

                elif mode_label == "Manevra":
                    required_de_power_for_prop = current_P_pervane_hedef * PROPULSION_PATH_INV_EFFICIENCY
                    de_power_for_auxiliary = p_current_aux_power_demand_kw if p_current_aux_power_demand_kw > 0 else 0.0
                    total_de_power_for_get_best_combination = required_de_power_for_prop + de_power_for_auxiliary
                
                if total_de_power_for_get_best_combination <= 0 or not np.isfinite(total_de_power_for_get_best_combination):
                    continue

                # DEĞİŞİKLİK: get_best_combination'a ALL_SFOC_CURVES sözlüğü veriliyor.
                fuel_total, combo_label_used, loads_info_list, original_main_details = get_best_combination(
                    total_de_power_for_get_best_combination,
                    p_main_gen_mcr, p_main_gen_qty, p_port_gen_mcr, p_port_gen_qty,
                    ALL_SFOC_CURVES,
                    duration
                )

                # Kodun geri kalanı orijinal haliyle korunuyor...
                if fuel_total > 0 and loads_info_list:
                    if mode_label == "Seyir": current_combo_total_sea_fuel_gens += fuel_total
                    else: current_combo_total_maneuver_fuel_gens += fuel_total
                    
                    original_fuel_val, original_label_val, is_assisted_val = np.nan, np.nan, False
                    if original_main_details and original_main_details[0] is not None:
                        original_fuel_val = round(original_main_details[0], 3)
                        original_label_val = original_main_details[1]
                        is_assisted_val = original_main_details[2]

                    detailed_data_list.append({
                        "Combo": gen_config_label, "SpecificComboUsed": combo_label_used, "Mode": mode_label,
                        "Shaft Power (kW)": current_P_pervane_hedef,
                        "Required DE Power (kW)": round(total_de_power_for_get_best_combination),
                        "Fuel (ton)": round(fuel_total, 3), "System Type": "Jeneratör",
                        "Load (%)": np.nan, "Gen Type": combo_label_used,
                        "N_running_combo": len(loads_info_list),
                        "OriginalMainOnlyFuel (ton)": original_fuel_val,
                        "OriginalMainOnlyLabel": original_label_val, "IsAssisted": is_assisted_val
                    })
                    for gen_mcr_running, load_percent_running, gen_kind_running in loads_info_list:
                        generator_usage_data_list.append({
                            "Combo": gen_config_label, "Mode": mode_label,
                            "Shaft Power (kW)": current_P_pervane_hedef,
                            "Required DE Power (kW)": round(total_de_power_for_get_best_combination),
                            "Gen MCR": gen_mcr_running, "Gen Kind": gen_kind_running,
                            "Gen Type": f"{gen_mcr_running} kW {gen_kind_running} Jen",
                            "Load Percent": round(load_percent_running, 2),
                            "N_running_combo": len(loads_info_list)
                        })
        
        # Orijinal kodun sonundaki özetleme mantığı korunuyor
        if current_combo_total_sea_fuel_gens > 0 or current_combo_total_maneuver_fuel_gens > 0:
            sea_diff = total_sea_fuel_main_engine_ref - current_combo_total_sea_fuel_gens
            maneuver_diff = total_maneuver_fuel_main_engine_ref - current_combo_total_maneuver_fuel_gens
            results_summary_list.append({
                "Jeneratör Konfigürasyonu": gen_config_label,
                "Toplam Seyir Yakıtı (Jeneratörler) (ton)": round(current_combo_total_sea_fuel_gens, 2),
                "Toplam Manevra Yakıtı (Jeneratörler) (ton)": round(current_combo_total_maneuver_fuel_gens, 2),
                "Seyir Yakıt Farkı (Ana M. Ref. - Jen) (ton)": round(sea_diff, 2),
                "Manevra Yakıt Farkı (Ana M. Ref. - Jen) (ton)": round(maneuver_diff, 2)
            })
        elif not results_summary_list and (total_sea_fuel_main_engine_ref > 0 or total_maneuver_fuel_main_engine_ref > 0):
             results_summary_list.append({
                "Jeneratör Konfigürasyonu": gen_config_label + " (Jeneratörler Çalıştırılamadı/Verimsiz)",
                "Toplam Seyir Yakıtı (Jeneratörler) (ton)": 0, "Toplam Manevra Yakıtı (Jeneratörler) (ton)": 0,
                "Seyir Yakıt Farkı (Ana M. Ref. - Jen) (ton)": round(total_sea_fuel_main_engine_ref, 2),
                "Manevra Yakıt Farkı (Ana M. Ref. - Jen) (ton)": round(total_maneuver_fuel_main_engine_ref, 2)
            })
        return pd.DataFrame(results_summary_list), pd.DataFrame(detailed_data_list), pd.DataFrame(generator_usage_data_list)

    # "HESAPLA" butonu fonksiyon çağrısı güncelleniyor
    if st.sidebar.button("Yeni Kombinasyon HESAPLA", key="nc_calculate_button"):
        if total_elec_eff_new_factor < 1e-9 and sea_power_range_new[1] > sea_power_range_new[0]:
             st.error("Hesaplama yapılamadı: Seyir modu için toplam elektriksel verimlilik faktörü çok düşük.")
             st.session_state.nc_show_results = False
             st.session_state.nc_results_df = pd.DataFrame(); st.session_state.nc_detailed_df = pd.DataFrame(); st.session_state.nc_usage_df = pd.DataFrame()
        elif nc_aux_power_demand_input > 0 and nc_conv_aux_dg_mcr_input <= 0 :
            st.error("Manevra için yardımcı güç ihtiyacı girilmiş ancak Referans Yardımcı DG MCR değeri pozitif değil.")
            st.session_state.nc_show_results = False
            st.session_state.nc_results_df = pd.DataFrame(); st.session_state.nc_detailed_df = pd.DataFrame(); st.session_state.nc_usage_df = pd.DataFrame()
        else:
            # DEĞİŞİKLİK: Fonksiyon çağrısından p_sfoc_data argümanı kaldırılıyor.
            st.session_state.nc_results_df, st.session_state.nc_detailed_df, st.session_state.nc_usage_df = \
                calculate_all_results_for_new_combinations(
                    main_gen_mcr_new, main_gen_qty_new, port_gen_mcr_new, port_gen_qty_new,
                    sea_power_range_new, maneuver_power_range_new,
                    sea_duration_new, maneuver_duration_new,
                    main_engine_mcr_ref_new,
                    total_elec_eff_new_factor,
                    CONVENTIONAL_SHAFT_EFFICIENCY,
                    nc_aux_power_demand_input,
                    nc_conv_aux_dg_mcr_input
                )
            st.session_state.nc_show_results = True
            if st.session_state.nc_results_df.empty and st.session_state.nc_detailed_df.empty:
                st.warning("Hesaplama yapıldı ancak 'Yeni Kombinasyonlar' için gösterilecek sonuç bulunamadı.")
                
    # --- Sonuçları Göster (Bu kısım öncekiyle aynı kalabilir) ---
    if st.session_state.nc_show_results and not st.session_state.nc_results_df.empty:
        st.subheader("Özet Sonuçlar (Yeni Kombinasyon)")
        st.dataframe(st.session_state.nc_results_df.style.format({
            "Seyirde Yakılan Yakıt (DE) (ton)": "{:.2f}",
            "Manevrada Yakılan Yakıt (DE) (ton)": "{:.2f}",
            "Seyir Yakıt Farkı (ton)": "{:.2f}",
            "Manevra Yakıt Farkı (ton)": "{:.2f}"
        }), use_container_width=True)

        st.markdown("---")
        st.subheader("Detaylı Grafiksel Analiz (Yeni Kombinasyon)")

        plot_data_source_nc = st.session_state.nc_detailed_df[
            (st.session_state.nc_detailed_df["Fuel (ton)"].notna()) &
            (st.session_state.nc_detailed_df["Fuel (ton)"] > 0)
        ].copy()

        if not plot_data_source_nc.empty:
            plot_mode_nc = st.radio(
                "Analiz Modunu Seçin (Yeni Kombinasyon)", ["Seyir", "Manevra"],
                horizontal=True, key="nc_plot_mode_radio"
            )
            mode_filtered_data_nc = plot_data_source_nc[plot_data_source_nc["Mode"] == plot_mode_nc].copy()
            
            plot_df_transformed_list_nc = []
            if not mode_filtered_data_nc.empty:
                mode_filtered_data_nc = mode_filtered_data_nc.sort_values(by="Shaft Power (kW)")
                for _, row in mode_filtered_data_nc.iterrows():
                    display_label = row["SpecificComboUsed"]
                    if row["System Type"] == "Ana Makine":
                        display_label = "Ana Makine Referans"
                        plot_df_transformed_list_nc.append({
                            "Shaft Power (kW)": row["Shaft Power (kW)"], "Fuel (ton)": row["Fuel (ton)"],
                            "DisplayCombo": display_label, "Mode": row["Mode"]
                        })
                    elif row["System Type"] == "Jeneratör":
                        plot_df_transformed_list_nc.append({
                            "Shaft Power (kW)": row["Shaft Power (kW)"], "Fuel (ton)": row["Fuel (ton)"],
                            "DisplayCombo": display_label, "Mode": row["Mode"]
                        })
                        if row["IsAssisted"] and pd.notna(row["OriginalMainOnlyFuel (ton)"]) and pd.notna(row["OriginalMainOnlyLabel"]):
                            plot_df_transformed_list_nc.append({
                                "Shaft Power (kW)": row["Shaft Power (kW)"], "Fuel (ton)": row["OriginalMainOnlyFuel (ton)"],
                                "DisplayCombo": f"{row['OriginalMainOnlyLabel']} (Karşılaştırma Ref.)", "Mode": row["Mode"]
                            })
            
            transformed_plot_df_nc = pd.DataFrame(plot_df_transformed_list_nc)
            
            if not transformed_plot_df_nc.empty:
                transformed_plot_df_nc['DisplayCombo'] = transformed_plot_df_nc['DisplayCombo'].astype('category')
                transformed_plot_df_nc = transformed_plot_df_nc.sort_values(by=["Shaft Power (kW)", "DisplayCombo"])
                fig_fuel_comp_nc = px.bar(
                    transformed_plot_df_nc, x="Shaft Power (kW)", y="Fuel (ton)", color="DisplayCombo",
                    barmode="group",
                    title=f"Yakıt Tüketimi Karşılaştırması ({plot_mode_nc} Modu - Yeni Kombinasyon)",
                    labels={"Fuel (ton)": "Yakıt (ton)", "Shaft Power (kW)": "Şaft Gücü (kW)", "DisplayCombo": "Sistem / Kombinasyon"}
                )
                fig_fuel_comp_nc.update_layout(bargap=0.1, bargroupgap=0.05)
                st.plotly_chart(fig_fuel_comp_nc, use_container_width=True)
            else:
                st.warning(f"{plot_mode_nc} modu için gösterilecek karşılaştırmalı yakıt verisi bulunamadı (dönüşüm sonrası).")
        else:
            st.warning("Yeni jeneratör kombinasyonu veya Ana Makine Referansına ait gösterilecek yakıt verisi bulunamadı (kaynak veri boş).")

        # --- Jeneratör Kullanım Grafiği (Yeni Kombinasyon) ---
        usage_plot_data_raw_nc = st.session_state.nc_usage_df[
            (st.session_state.nc_usage_df["Mode"] == plot_mode_nc) &
            (st.session_state.nc_usage_df["Load Percent"].notna())
        ].copy()

        if not usage_plot_data_raw_nc.empty:
            if plot_mode_nc == "Seyir":
                usage_summary_list_nc = []
                for de_power_val, group in usage_plot_data_raw_nc.groupby("Required DE Power (kW)"):
                    if not group.empty:
                        detail_match = st.session_state.nc_detailed_df[
                            (st.session_state.nc_detailed_df["Mode"] == plot_mode_nc) &
                            (st.session_state.nc_detailed_df["Required DE Power (kW)"] == de_power_val) &
                            (st.session_state.nc_detailed_df["System Type"] == "Jeneratör")
                        ]
                        running_config_label = "N/A"; num_total_gens = 0; avg_load_primary = 0
                        if not detail_match.empty:
                            running_config_label = detail_match.iloc[0]["SpecificComboUsed"]
                            num_total_gens = detail_match.iloc[0]["N_running_combo"]
                        
                        main_gen_loads = group[group["Gen Kind"] == "Ana"]["Load Percent"]
                        if not main_gen_loads.empty: avg_load_primary = main_gen_loads.mean()
                        else:
                            port_gen_loads = group[group["Gen Kind"] == "Liman"]["Load Percent"]
                            if not port_gen_loads.empty: avg_load_primary = port_gen_loads.mean()
                            elif not group.empty: avg_load_primary = group["Load Percent"].iloc[0]
                        
                        usage_summary_list_nc.append({
                            "Required DE Power (kW)": de_power_val,
                            "Running Config": running_config_label,
                            "Representative Load (%)": round(avg_load_primary, 1) if avg_load_primary else 0,
                            "Number of Generators": num_total_gens
                        })
                
                usage_plot_df_nc = pd.DataFrame(usage_summary_list_nc).drop_duplicates().sort_values(by="Required DE Power (kW)")
                if not usage_plot_df_nc.empty:
                    fig_usage_nc_seyir = px.bar(
                        usage_plot_df_nc, x="Required DE Power (kW)", y="Representative Load (%)",
                        text="Representative Load (%)", hover_data=["Running Config", "Number of Generators"],
                        title=f"Jeneratör Yükleri ({plot_mode_nc} Modu - Yeni Kombinasyon)",
                        labels={"Representative Load (%)": "Temsili Jeneratör Yükü (%)", "Required DE Power (kW)": "Gerekli DE Gücü (kW)"}
                    )
                    fig_usage_nc_seyir.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                    fig_usage_nc_seyir.update_yaxes(range=[0, 110])
                    st.plotly_chart(fig_usage_nc_seyir, use_container_width=True)
                else: st.warning(f"{plot_mode_nc} modu için özetlenmiş jeneratör kullanım verisi bulunamadı.")
            else: # Manevra modu
                usage_plot_df_nc = usage_plot_data_raw_nc.sort_values(by=["Required DE Power (kW)", "Gen Type"])
                if not usage_plot_df_nc.empty:
                    fig_usage_nc_manevra = px.bar(
                        usage_plot_df_nc, x="Required DE Power (kW)", y="Load Percent", color="Gen Type",
                        barmode="group", text_auto=".1f",
                        title=f"Jeneratör Yük Dağılımı ({plot_mode_nc} Modu - Yeni Kombinasyon)",
                        labels={"Load Percent": "Yük Yüzdesi (%)", "Required DE Power (kW)": "Gerekli DE Gücü (kW)", "Gen Type": "Jeneratör Tipi"}
                    )
                    fig_usage_nc_manevra.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
                    fig_usage_nc_manevra.update_yaxes(range=[0, 110])
                    fig_usage_nc_manevra.update_layout(bargroupgap=0.05)
                    st.plotly_chart(fig_usage_nc_manevra, use_container_width=True)
                else: st.warning(f"{plot_mode_nc} modu için jeneratör kullanım verisi bulunamadı.")
        else:
            st.warning(f"{plot_mode_nc} modu için jeneratör kullanım verisi bulunamadı (işlenmemiş veri boş).")

    elif st.session_state.nc_show_results and st.session_state.nc_results_df.empty:
        st.warning("Yeni kombinasyon için hesaplama yapıldı ancak özetlenecek sonuç bulunamadı...")
        if st.session_state.nc_detailed_df.empty:
            st.error("Detaylı sonuçlar da boş (Yeni Kombinasyon). Girdi değerlerinizi, SFOC verilerini ve jeneratör konfigürasyonunu tekrar kontrol edin.")
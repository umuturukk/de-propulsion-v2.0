# core_calculations.py
import numpy as np
from scipy.interpolate import interp1d

# --- Ortak Hesaplama Fonksiyonları ---
def determine_generator_usage(total_power, unit_power):
    if unit_power <= 0: return None, None
    if total_power <= 0: return 0, 0.0
    for n in range(1, 4):
        load_per_gen = (total_power / (n * unit_power)) * 100
        if 40 <= load_per_gen <= 92:
            return n, load_per_gen
    return None, None

def interpolate_sfoc_non_linear(load_percentage, sfoc_data_input):
    if not isinstance(sfoc_data_input, dict) or len(sfoc_data_input) < 2: return None
    loads = list(sfoc_data_input.keys())
    sfocs = list(sfoc_data_input.values())
    sorted_indices = np.argsort(loads)
    sorted_loads = np.array(loads)[sorted_indices]
    sorted_sfocs = np.array(sfocs)[sorted_indices]
    if len(sorted_loads) < 2: return None
    try:
        interp_func = interp1d(sorted_loads, sorted_sfocs, kind='quadratic', fill_value="extrapolate")
        sfoc_value = float(interp_func(load_percentage))
        return sfoc_value
    except ValueError as e: return None

def calculate_fuel(power_output_kw, load_percent_on_engine, duration_hr, sfoc_data_input):
    if power_output_kw <= 0 or duration_hr <= 0: return 0.0
    sfoc = interpolate_sfoc_non_linear(load_percent_on_engine, sfoc_data_input)
    if sfoc is None or sfoc < 50: return 0.0
    return (power_output_kw * duration_hr * sfoc) / 1_000_000

def calculate_power_flow(shaft_power, motor_eff, converter_eff, switchboard_eff, generator_alternator_eff):
    if shaft_power <= 0: return None, None
    if not all([motor_eff > 0, converter_eff > 0, switchboard_eff > 0, generator_alternator_eff > 0]): return None, None
    p_shaft = shaft_power; p_motor_input = p_shaft / motor_eff; p_converter_input = p_motor_input / converter_eff
    p_switchboard_input_from_gens = p_converter_input / switchboard_eff; p_alternator_elec_output = p_switchboard_input_from_gens
    p_alternator_mech_input = p_alternator_elec_output / generator_alternator_eff
    if any([not np.isfinite(val) for val in [p_motor_input, p_converter_input, p_switchboard_input_from_gens, p_alternator_mech_input]]): return None, None
    loss_motor = p_motor_input - p_shaft; loss_converter = p_converter_input - p_motor_input
    loss_switchboard = p_switchboard_input_from_gens - p_converter_input; loss_alternator = p_alternator_mech_input - p_alternator_elec_output
    power_values = { "shaft": p_shaft, "motor_input": p_motor_input, "converter_input": p_converter_input, "switchboard_input_from_gens": p_switchboard_input_from_gens, "alternator_elec_output": p_alternator_elec_output, "alternator_mech_input": p_alternator_mech_input }
    loss_values = { "motor": loss_motor, "converter": loss_converter, "switchboard": loss_switchboard, "alternator": loss_alternator }
    return power_values, loss_values

def find_min_gens_for_power(required_power, unit_mcr, unit_qty):
    if unit_mcr <= 0 or unit_qty <= 0: return None
    if required_power <= 0: return 0
    min_gens = np.ceil(required_power / unit_mcr)
    return int(min_gens) if min_gens <= unit_qty else None

def evaluate_combination(required_de_power, running_gens_info, sfoc_curves, duration):
    if not running_gens_info: return None
    running_mcrs = [mcr for mcr, gen_type in running_gens_info]
    total_running_capacity = sum(running_mcrs)
    if total_running_capacity <= 0 or required_de_power <= 0: return None
    # İstenen güç, toplam kapasitenin çok az üzerinde olabilir, buna izin ver (örn. yuvarlama hataları için)
    if required_de_power > total_running_capacity * 1.001: return None # %0.1 tolerans
    
    power_per_gen_list = []
    if total_running_capacity > 0:
        # Güç, çalışan jeneratörlerin kapasiteleriyle orantılı olarak dağıtılır
        power_per_gen_list = [(required_de_power * gen_mcr / total_running_capacity) for gen_mcr in running_mcrs]
    else: # total_running_capacity = 0 ise (yukarıda kontrol edildi ama yine de)
        power_per_gen_list = [0 for _ in running_mcrs]

    load_percent_list = [(power / mcr * 100) if mcr > 0 else 0 for power, mcr in zip(power_per_gen_list, running_mcrs)]
    
    total_fuel_for_combination = 0
    loads_info_for_combination = []
    valid_fuel_calculations = 0

    for i in range(len(running_gens_info)):
        gen_mcr, gen_type_label = running_gens_info[i]
        load_percentage_on_gen = load_percent_list[i]
        power_output_of_gen = power_per_gen_list[i]

        if load_percentage_on_gen > 110: return None # Aşırı yüklenme durumu

        sfoc_key = 'main_de_gen' if gen_type_label == "Ana" else 'port_gen'
        sfoc_data_for_gen = sfoc_curves.get(sfoc_key)
        if sfoc_data_for_gen is None:
            # print(f"Uyarı: {sfoc_key} için SFOC verisi bulunamadı. Kombinasyon atlanıyor.")
            return None # SFOC verisi yoksa bu kombinasyon geçersiz

        fuel_part = calculate_fuel(power_output_of_gen, load_percentage_on_gen, duration, sfoc_data_for_gen)
        
        if fuel_part is None: # calculate_fuel None dönerse (örn. SFOC < 50)
            return None # Bu kombinasyon geçersiz
        
        # Eğer güç çekiliyorsa ama yakıt 0 ise (örn. SFOC < 50 nedeniyle calculate_fuel 0 döndürdüyse)
        # Bu durumu da geçersiz sayabiliriz, çünkü bu jeneratör verimsizdir.
        if power_output_of_gen > 0 and fuel_part <= 0:
            return None


        total_fuel_for_combination += fuel_part
        loads_info_for_combination.append((gen_mcr, load_percentage_on_gen, gen_type_label))
        valid_fuel_calculations += 1
            
    if valid_fuel_calculations == len(running_gens_info) and total_fuel_for_combination > 0:
        return total_fuel_for_combination, loads_info_for_combination
    elif required_de_power <= 0 and valid_fuel_calculations == len(running_gens_info) : # Yük yoksa ve tüm jen. 0 yükteyse
        return 0.0, loads_info_for_combination # Yakıt 0, ama geçerli bir "yüksüz" durum
    else:
        return None

def get_best_combination(required_de_power, main_mcr, main_qty, port_mcr, port_qty, sfoc_curves, duration):
    if required_de_power <= 0:
        return 0.0, "0 kW Yük (Yakıt Yok)", [], (None, None, False)

    evaluated_options = {}

    def add_option(key, fuel, label, loads, original_info_tuple=None):
        # Sadece daha iyi (düşük) yakıt tüketimi olanı veya ilk bulunanı sakla
        if key not in evaluated_options or fuel < evaluated_options[key][0]:
            evaluated_options[key] = (fuel, label, loads, original_info_tuple)

    main_only_inefficient_candidate_fuel = None
    main_only_inefficient_candidate_label = None
    main_only_inefficient_candidate_loads = None
    original_main_info_tuple_for_assisted_strategy = None 

    # --- STRATEJİ 1: SADECE ANA JENERATÖRLER ---
    if main_qty > 0 and main_mcr > 0:
        n_main1 = find_min_gens_for_power(required_de_power, main_mcr, main_qty)
        if n_main1 is not None:
            eval_res1 = evaluate_combination(required_de_power, [(main_mcr, "Ana")] * n_main1, sfoc_curves, duration)
            if eval_res1:
                fuel1, loads1 = eval_res1; label1 = f"{n_main1}x {main_mcr}kW Ana"; load_pct1 = loads1[0][1] if loads1 else 100.0
                if 65 <= load_pct1 <= 92: add_option("main_eff", fuel1, label1, loads1)
                elif load_pct1 < 65:
                    main_only_inefficient_candidate_fuel = fuel1; main_only_inefficient_candidate_label = label1
                    main_only_inefficient_candidate_loads = loads1; add_option("main_ineff_low", fuel1, label1, loads1)
                    original_main_info_tuple_for_assisted_strategy = (fuel1, label1, True)
                elif load_pct1 > 92 and n_main1 + 1 <= main_qty:
                    n_main2 = n_main1 + 1
                    if n_main2 * main_mcr >= required_de_power:
                        eval_res2 = evaluate_combination(required_de_power, [(main_mcr, "Ana")] * n_main2, sfoc_curves, duration)
                        if eval_res2:
                            fuel2, loads2 = eval_res2; label2 = f"{n_main2}x {main_mcr}kW Ana"; load_pct2 = loads2[0][1] if loads2 else 100.0
                            if 65 <= load_pct2 <= 92: add_option("main_eff_plus_one", fuel2, label2, loads2)
                            elif load_pct2 < 65:
                                if main_only_inefficient_candidate_fuel is None or fuel2 < main_only_inefficient_candidate_fuel:
                                    main_only_inefficient_candidate_fuel = fuel2; main_only_inefficient_candidate_label = label2
                                    main_only_inefficient_candidate_loads = loads2
                                    original_main_info_tuple_for_assisted_strategy = (fuel2, label2, True)
                                add_option("main_ineff_low_plus_one", fuel2, label2, loads2)
                            else: add_option("main_fallback_plus_one", fuel2, label2, loads2)
                else: add_option("main_fallback_at_n_main1", fuel1, label1, loads1)

    # --- STRATEJİ 2: SADECE LİMAN JENERATÖR(LER)İ ---
    if port_qty > 0 and port_mcr > 0:
        n_port = find_min_gens_for_power(required_de_power, port_mcr, port_qty)
        if n_port is not None and n_port > 0:
            eval_res_port = evaluate_combination(required_de_power, [(port_mcr, "Liman")] * n_port, sfoc_curves, duration)
            if eval_res_port:
                fuel_p, loads_p = eval_res_port; label_p = f"{n_port}x {port_mcr}kW Liman"
                add_option("port_only", fuel_p, label_p, loads_p)

    # --- STRATEJİ 3: DESTEKLİ MOD ---
    best_overall_assisted_fuel = float('inf')
    best_overall_assisted_details = None
    
    if main_only_inefficient_candidate_fuel is not None and \
       port_qty >= 1 and port_mcr > 0 and main_qty >= 1:
        
        num_main_in_inefficient_case = sum(1 for _, _, gen_type in main_only_inefficient_candidate_loads if gen_type == "Ana") if main_only_inefficient_candidate_loads else 0
        n_main_options_for_assisted = sorted(list(set(n for n in [num_main_in_inefficient_case - 1, 1, num_main_in_inefficient_case] if 0 < n <= main_qty)))
        if not n_main_options_for_assisted and main_qty > 0: n_main_options_for_assisted.append(1)
        
        # `original_main_info_tuple_for_assisted_strategy` Strateji 1'de ayarlandı.
        current_original_main_info_for_assisted = original_main_info_tuple_for_assisted_strategy

        for n_main_assisted_try in n_main_options_for_assisted:
            # Liman jeneratörünün yük aralığı: %50 ile %89 arasında 5'er adımlarla.
            # Önceki kodda range(89, 49, -5) idi, bu %89, %84, ..., %54, %49 yapar.
            # İstenen aralık %60-%85 ise range(85, 59, -5) olmalıydı.
            # %50-%89 için:
            for target_port_load_percentage_try in range(89, 49, -5): 
                port_gen_power_output_try = port_mcr * (target_port_load_percentage_try / 100.0)
                if port_gen_power_output_try > required_de_power + 1e-3 : continue
                
                remaining_power_for_main_gens_try = required_de_power - port_gen_power_output_try
                
                current_main_gens_power_output_per_gen_try = 0.0
                current_main_gens_load_percentage_try = 0.0

                if remaining_power_for_main_gens_try <= 1e-3 : # Liman jen. tüm yükü karşılıyor veya aşıyor
                    if n_main_assisted_try > 0: continue # Ana jen. çalışmamalı
                    remaining_power_for_main_gens_try = 0 # Ana jen. yükü sıfır
                elif n_main_assisted_try > 0: # Ana jeneratörler devredeyse
                    if n_main_assisted_try * main_mcr < remaining_power_for_main_gens_try - 1e-3: continue # Ana jen. kapasitesi yetersiz
                    current_main_gens_power_output_per_gen_try = remaining_power_for_main_gens_try / n_main_assisted_try
                    current_main_gens_load_percentage_try = (current_main_gens_power_output_per_gen_try / main_mcr) * 100
                    # Ana jeneratör yük kontrolü: Örneğin %65-%90 aralığı daha verimli olabilir.
                    # Şimdilik daha geniş bir aralık olan %50-%92 kullanalım.
                    if not (50.0 <= current_main_gens_load_percentage_try <= 92.0 + 1e-9): continue 
                else: # Kalan güç var ama çalışacak ana jen. sayısı 0, bu senaryo geçersiz.
                    continue 

                fuel_port_try = calculate_fuel(port_gen_power_output_try, target_port_load_percentage_try, duration, sfoc_curves['port_gen'])
                if fuel_port_try is None or (fuel_port_try == 0 and port_gen_power_output_try > 1e-3): continue # Yakıt hesaplanamadı veya 0 ise geçersiz
                
                total_fuel_main_try = 0.0
                if n_main_assisted_try > 0 and current_main_gens_power_output_per_gen_try > 1e-3:
                    fuel_main_part_try = calculate_fuel(current_main_gens_power_output_per_gen_try, current_main_gens_load_percentage_try, duration, sfoc_curves['main_de_gen'])
                    if fuel_main_part_try is None or (fuel_main_part_try == 0 and current_main_gens_power_output_per_gen_try > 1e-3): continue # Yakıt hesaplanamadı veya 0 ise geçersiz
                    total_fuel_main_try = fuel_main_part_try * n_main_assisted_try
                
                current_total_fuel_for_this_assisted_option = (fuel_port_try if fuel_port_try else 0) + total_fuel_main_try
                if current_total_fuel_for_this_assisted_option <= 0 : continue # Toplam yakıt 0 veya negatifse geçersiz

                # Bu destekli mod, 'main_only_inefficient_candidate_fuel'den daha iyi olmalı VE
                # o ana kadar bulunan en iyi destekli moddan da daha iyi olmalı.
                if current_total_fuel_for_this_assisted_option < main_only_inefficient_candidate_fuel and \
                   current_total_fuel_for_this_assisted_option < best_overall_assisted_fuel:
                    best_overall_assisted_fuel = current_total_fuel_for_this_assisted_option
                    loads_info_for_best_assisted = []
                    label_parts_for_best_assisted = []
                    if port_gen_power_output_try > 1e-3:
                        loads_info_for_best_assisted.append((port_mcr, target_port_load_percentage_try, "Liman"))
                        label_parts_for_best_assisted.append(f"1x{port_mcr}kW Liman ({target_port_load_percentage_try:.1f}%)")
                    if n_main_assisted_try > 0 and current_main_gens_power_output_per_gen_try > 1e-3:
                        for _ in range(n_main_assisted_try):
                            loads_info_for_best_assisted.append((main_mcr, current_main_gens_load_percentage_try, "Ana"))
                        label_parts_for_best_assisted.insert(0, f"{n_main_assisted_try}x{main_mcr}kW Ana ({current_main_gens_load_percentage_try:.1f}%)")
                    if loads_info_for_best_assisted:
                        final_label_for_best_assisted = " + ".join(label_parts_for_best_assisted)
                        best_overall_assisted_details = (best_overall_assisted_fuel, final_label_for_best_assisted, loads_info_for_best_assisted, original_main_info_tuple_for_assisted_strategy)

    if best_overall_assisted_details:
        add_option("assisted_optimal", best_overall_assisted_details[0], best_overall_assisted_details[1], best_overall_assisted_details[2], best_overall_assisted_details[3])

    # --- KARAR VERME MANTIĞI (Yeniden Düzenlenmiş) ---
    final_choice_key = None
    current_best_fuel = float('inf')

    # 1. Öncelikle en verimli ana jeneratör seçeneklerini değerlendir.
    for key in ["main_eff", "main_eff_plus_one"]:
        if key in evaluated_options:
            if evaluated_options[key][0] < current_best_fuel:
                current_best_fuel = evaluated_options[key][0]
                final_choice_key = key
    
    # 2. Ardından, bulunan en iyi destekli modu değerlendir.
    # Eğer destekli mod, o ana kadar bulunan en iyi seçenekten (verimli ana jen.) daha iyiyse, onu seç.
    if "assisted_optimal" in evaluated_options:
        if evaluated_options["assisted_optimal"][0] < current_best_fuel:
            current_best_fuel = evaluated_options["assisted_optimal"][0]
            final_choice_key = "assisted_optimal"

    # 3. Sonra, sadece liman jeneratörünü değerlendir.
    # Eğer o ana kadar bulunan en iyi seçenekten daha iyiyse, onu seç.
    if "port_only" in evaluated_options:
        if evaluated_options["port_only"][0] < current_best_fuel:
            current_best_fuel = evaluated_options["port_only"][0]
            final_choice_key = "port_only"

    # 4. Fallback: Eğer yukarıdaki öncelikli adımlar sonucunda bir `final_choice_key` atanamadıysa
    #    VEYA atanan seçenek, `evaluated_options` içindeki diğer (daha önce önceliklendirilmemiş)
    #    seçeneklerden (örn: "main_ineff_low", "main_fallback_at_n_main1") birinden daha KÖTÜ ise,
    #    o zaman `evaluated_options` içindeki TÜM seçenekler arasından MUTLAK EN İYİYİ seç.
    #    Bu, "assisted_optimal" veya "port_only" gibi bir seçeneğin, gözden kaçan daha iyi bir
    #    "main_ineff_low" gibi bir durumdan daha kötü olması durumunda devreye girer.
    #    Aynı zamanda, eğer sadece "main_ineff_low" gibi bir seçenek varsa, onun seçilmesini sağlar.

    if evaluated_options: # Eğer en az bir değerlendirilmiş seçenek varsa
        # Tüm seçenekler arasından en düşük yakıt tüketimine sahip olanı bul
        absolute_best_key_from_all = min(evaluated_options, key=lambda k: evaluated_options[k][0])
        absolute_best_fuel_from_all = evaluated_options[absolute_best_key_from_all][0]

        if final_choice_key is None or absolute_best_fuel_from_all < current_best_fuel:
            # Eğer hiç seçim yapılmadıysa VEYA tüm seçenekler arasındaki en iyi,
            # öncelikli seçimlerden daha iyiyse, mutlak en iyiyi seç.
            final_choice_key = absolute_best_key_from_all
            # current_best_fuel'i güncellemeye gerek yok, zaten en iyiyi bulduk.

    if final_choice_key:
        fuel, label, loads, original_info = evaluated_options[final_choice_key]
        is_assisted_flag_from_key = "assisted" in final_choice_key 
        if original_info:
             final_original_info_tuple = (original_info[0], original_info[1], original_info[2] if len(original_info) == 3 else is_assisted_flag_from_key)
        else:
            final_original_info_tuple = (None, None, is_assisted_flag_from_key)
        return fuel, label, loads, final_original_info_tuple
    else:
        # Bu noktaya gelinmemesi lazım eğer evaluated_options boş değilse, ama bir güvenlik önlemi.
        return 0.0, "Uygun Kombinasyon Yok (Karar Verilemedi)", [], (None, None, False)
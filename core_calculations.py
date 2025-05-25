# core_calculations.py
import numpy as np
from scipy.interpolate import interp1d

# Bu modüldeki fonksiyonlar genellikle argüman olarak sfoc_data alır.

# --- Ortak Hesaplama Fonksiyonları ---

def determine_generator_usage(total_power, unit_power):
    """
    Yük paylaşımı kurallarına göre çalışan jeneratör sayısını belirler.
    (Orijinal "Yakıt Analizi" sayfasındaki mantık)
    """
    if unit_power <= 0:
        return None, None
    if total_power <= 0:
        return 0, 0.0  # Yük yoksa 0 jeneratör

    # Max 3 jeneratör varsayımı (orijinal koddaki for n in range(1, 4) döngüsüne göre)
    # Eğer daha fazla jeneratör tipi paralel çalışabiliyorsa bu mantık genişletilmeli.
    for n in range(1, 4):
        # Jeneratör başına düşen yük (%) = (Toplam Güç / (Çalışan Jen. Sayısı * Birim Jen. Gücü)) * 100
        load_per_gen = (total_power / (n * unit_power)) * 100
        # Jeneratörlerin %40-%92 yük aralığında çalışması kuralı
        if 40 <= load_per_gen <= 92:
            return n, load_per_gen
    return None, None # Uygun kombinasyon bulunamadı

def interpolate_sfoc_non_linear(load_percentage, sfoc_data_input):
    """
    Verilen yük yüzdesi için SFOC değerini karesel interpolasyon ile hesaplar.
    """
    if not isinstance(sfoc_data_input, dict) or len(sfoc_data_input) < 2:
        return None
        
    loads = list(sfoc_data_input.keys())
    sfocs = list(sfoc_data_input.values())

    sorted_indices = np.argsort(loads)
    sorted_loads = np.array(loads)[sorted_indices]
    sorted_sfocs = np.array(sfocs)[sorted_indices]

    if len(sorted_loads) < 2:
        return None

    try:
        interp_func = interp1d(sorted_loads, sorted_sfocs, kind='quadratic', fill_value="extrapolate")
        sfoc_value = float(interp_func(load_percentage))
        return sfoc_value
    except ValueError as e:
        return None

def calculate_fuel(power_output_kw, load_percent_on_engine, duration_hr, sfoc_data_input):
    """
    Verilen parametreler için yakıt tüketimini ton olarak hesaplar.
    """
    if power_output_kw <= 0 or duration_hr <= 0:
        return 0.0

    sfoc = interpolate_sfoc_non_linear(load_percent_on_engine, sfoc_data_input)

    if sfoc is None or sfoc < 50:
        return 0.0
    
    return (power_output_kw * duration_hr * sfoc) / 1_000_000

# --- Güç Akış Diyagramı için Hesaplamalar ("Yakıt Analizi" sayfası) ---
def calculate_power_flow(shaft_power, motor_eff, converter_eff, switchboard_eff, generator_alternator_eff):
    # Bu fonksiyonda değişiklik yok
    if shaft_power <= 0:
        return None, None
    if not all([motor_eff > 0, converter_eff > 0, switchboard_eff > 0, generator_alternator_eff > 0]):
        return None, None

    p_shaft = shaft_power
    p_motor_input = p_shaft / motor_eff
    p_converter_input = p_motor_input / converter_eff
    p_switchboard_input_from_gens = p_converter_input / switchboard_eff
    p_alternator_elec_output = p_switchboard_input_from_gens
    p_alternator_mech_input = p_alternator_elec_output / generator_alternator_eff

    if any([not np.isfinite(val) for val in [p_motor_input, p_converter_input, p_switchboard_input_from_gens, p_alternator_mech_input]]):
        return None, None

    loss_motor = p_motor_input - p_shaft
    loss_converter = p_converter_input - p_motor_input
    loss_switchboard = p_switchboard_input_from_gens - p_converter_input
    loss_alternator = p_alternator_mech_input - p_alternator_elec_output

    power_values = {
        "shaft": p_shaft, "motor_input": p_motor_input, "converter_input": p_converter_input,
        "switchboard_input_from_gens": p_switchboard_input_from_gens,
        "alternator_elec_output": p_alternator_elec_output, "alternator_mech_input": p_alternator_mech_input
    }
    loss_values = { "motor": loss_motor, "converter": loss_converter, "switchboard": loss_switchboard, "alternator": loss_alternator }
    return power_values, loss_values

# --- "Yeni Jeneratör Kombinasyonları" sayfası için Yardımcı Fonksiyonlar ---
def find_min_gens_for_power(required_power, unit_mcr, unit_qty):
    # Bu fonksiyonda değişiklik yok
    if unit_mcr <= 0 or unit_qty <= 0:
        return None
    if required_power <= 0:
        return 0

    min_gens = np.ceil(required_power / unit_mcr)
    return int(min_gens) if min_gens <= unit_qty else None

# DEĞİŞİKLİK 1: evaluate_combination, artık tek bir sfoc_data yerine sfoc_curves sözlüğü alıyor.
def evaluate_combination(required_de_power, running_gens_info, sfoc_curves, duration):
    """
    Belirli bir çalışan jeneratör kombinasyonunun yakıtını, doğru SFOC eğrisini kullanarak değerlendirir.
    """
    if not running_gens_info:
        return None

    running_mcrs = [mcr for mcr, gen_type in running_gens_info]
    total_running_capacity = sum(running_mcrs)

    if total_running_capacity <= 0 or required_de_power <= 0:
        return None
    
    if required_de_power > total_running_capacity * 1.001:
        return None

    power_per_gen_list = []
    if total_running_capacity > 0:
        power_per_gen_list = [(required_de_power * gen_mcr / total_running_capacity) for gen_mcr in running_mcrs]
    else:
        power_per_gen_list = [0 for _ in running_mcrs]

    load_percent_list = [(power / mcr * 100) if mcr > 0 else 0 for power, mcr in zip(power_per_gen_list, running_mcrs)]

    total_fuel_for_combination = 0
    loads_info_for_combination = []
    valid_fuel_calculations = 0

    for i in range(len(running_gens_info)):
        gen_mcr, gen_type_label = running_gens_info[i]
        load_percentage_on_gen = load_percent_list[i]
        power_output_of_gen = power_per_gen_list[i]

        if load_percentage_on_gen > 110:
            return None # Kombinasyon geçersiz

        # Jeneratör tipine göre doğru SFOC verisini seç
        sfoc_key = 'main_de_gen' if gen_type_label == "Ana" else 'port_gen'
        sfoc_data_for_gen = sfoc_curves.get(sfoc_key)

        if sfoc_data_for_gen is None:
            continue # Bu jeneratör için SFOC verisi yoksa atla

        fuel_part = calculate_fuel(power_output_of_gen, load_percentage_on_gen, duration, sfoc_data_for_gen)

        if fuel_part is not None and fuel_part > 0:
            total_fuel_for_combination += fuel_part
            loads_info_for_combination.append((gen_mcr, load_percentage_on_gen, gen_type_label))
            valid_fuel_calculations += 1
        elif power_output_of_gen > 0:
             return None # Güç çekiliyor ama yakıt 0 ise, kombinasyon verimsizdir

    if valid_fuel_calculations > 0 and total_fuel_for_combination > 0:
        return total_fuel_for_combination, loads_info_for_combination
    else:
        return None

# DEĞİŞİKLİK 2: get_best_combination, artık sfoc_curves sözlüğü alıyor ve bunu alt fonksiyonlara iletiyor.
def get_best_combination(required_de_power, main_mcr, main_qty, port_mcr, port_qty, sfoc_curves, duration):
    """
    Verilen güç ihtiyacı için en iyi jeneratör kombinasyonunu, spesifik SFOC verilerini kullanarak bulur.
    """
    if required_de_power <= 0:
        return 0.0, "0 kW Yük (Yakıt Yok)", [], (None, None, False)

    evaluated_options = {}

    def add_option(key, fuel, label, loads, original_info_tuple=None):
        if key not in evaluated_options or fuel < evaluated_options[key][0]:
            evaluated_options[key] = (fuel, label, loads, original_info_tuple)

    main_only_inefficient_candidate_fuel = None
    main_only_inefficient_candidate_label = None
    main_only_inefficient_candidate_loads = None

    # --- STRATEJİ 1: SADECE ANA JENERATÖRLER ---
    if main_qty > 0 and main_mcr > 0:
        n_main1 = find_min_gens_for_power(required_de_power, main_mcr, main_qty)
        if n_main1 is not None:
            running_info1 = [(main_mcr, "Ana")] * n_main1
            eval_res1 = evaluate_combination(required_de_power, running_info1, sfoc_curves, duration)
            if eval_res1:
                fuel1, loads1 = eval_res1
                label1 = f"{n_main1}x {main_mcr}kW Ana"
                load_pct1 = loads1[0][1] if loads1 else 100.0

                if 65 <= load_pct1 <= 92:
                    add_option("main_eff", fuel1, label1, loads1)
                elif load_pct1 < 65:
                    main_only_inefficient_candidate_fuel = fuel1
                    main_only_inefficient_candidate_label = label1
                    main_only_inefficient_candidate_loads = loads1
                    add_option("main_ineff_low", fuel1, label1, loads1)
                elif load_pct1 > 92 and n_main1 + 1 <= main_qty:
                    n_main2 = n_main1 + 1
                    if n_main2 * main_mcr >= required_de_power:
                        running_info2 = [(main_mcr, "Ana")] * n_main2
                        eval_res2 = evaluate_combination(required_de_power, running_info2, sfoc_curves, duration)
                        if eval_res2:
                            fuel2, loads2 = eval_res2
                            label2 = f"{n_main2}x {main_mcr}kW Ana"
                            load_pct2 = loads2[0][1] if loads2 else 100.0
                            if 65 <= load_pct2 <= 92:
                                add_option("main_eff_plus_one", fuel2, label2, loads2)
                            else:
                                add_option("main_fallback_plus_one", fuel2, label2, loads2)
                else:
                    add_option("main_fallback_at_n_main1", fuel1, label1, loads1)

    # --- STRATEJİ 2: SADECE LİMAN JENERATÖR(LER)İ ---
    if port_qty > 0 and port_mcr > 0:
        n_port = find_min_gens_for_power(required_de_power, port_mcr, port_qty)
        if n_port is not None and n_port > 0:
            running_info_port = [(port_mcr, "Liman")] * n_port
            eval_res_port = evaluate_combination(required_de_power, running_info_port, sfoc_curves, duration)
            if eval_res_port:
                fuel_p, loads_p = eval_res_port
                label_p = f"{n_port}x {port_mcr}kW Liman"
                add_option("port_only", fuel_p, label_p, loads_p)

    # --- STRATEJİ 3: DESTEKLİ MOD (1 Liman Jen + N Ana Jen) ---
    if main_only_inefficient_candidate_fuel is not None and port_qty >= 1 and port_mcr > 0 and main_qty >= 1:
        original_main_info_for_assisted = (main_only_inefficient_candidate_fuel, main_only_inefficient_candidate_label, True)
        # Orijinal koddaki gibi denenecek ana jeneratör sayıları belirleniyor
        num_main_in_inefficient_case = 0
        if main_only_inefficient_candidate_loads:
            num_main_in_inefficient_case = sum(1 for _m, _l, gen_type in main_only_inefficient_candidate_loads if gen_type == "Ana")
        n_main_options_for_assisted = sorted(list(set(n for n in [num_main_in_inefficient_case - 1, 1, num_main_in_inefficient_case] if 0 < n <= main_qty)))
        if not n_main_options_for_assisted and main_qty > 0:
            n_main_options_for_assisted.append(1)

        for n_main_assisted in n_main_options_for_assisted:
            for target_port_load_percentage in range(85, 59, -5):
                port_gen_power_output = port_mcr * (target_port_load_percentage / 100.0)
                remaining_power_for_main_gens = required_de_power - port_gen_power_output

                # Liman jeneratörünün yakıtını kendi SFOC verisiyle hesapla
                fuel_port_in_assisted_mode = calculate_fuel(port_gen_power_output, target_port_load_percentage, duration, sfoc_curves['port_gen'])
                if fuel_port_in_assisted_mode is None or (fuel_port_in_assisted_mode <= 0 and port_gen_power_output > 1e-3):
                    continue

                total_fuel_main_in_assisted_mode = 0
                if remaining_power_for_main_gens > 1e-3:
                    if n_main_assisted * main_mcr < remaining_power_for_main_gens: continue
                    current_main_gens_power_output_per_gen = remaining_power_for_main_gens / n_main_assisted
                    current_main_gens_load_percentage = (current_main_gens_power_output_per_gen / main_mcr) * 100
                    if not (5.0 <= current_main_gens_load_percentage <= 92.0 + 1e-9): continue
                    
                    # Ana jeneratör yakıtını kendi SFOC verisiyle hesapla
                    fuel_main_part = calculate_fuel(current_main_gens_power_output_per_gen, current_main_gens_load_percentage, duration, sfoc_curves['main_de_gen'])
                    if fuel_main_part is None or (fuel_main_part <= 0 and current_main_gens_power_output_per_gen > 1e-3):
                        continue
                    total_fuel_main_in_assisted_mode = fuel_main_part * n_main_assisted
                
                current_total_fuel_assisted = fuel_port_in_assisted_mode + total_fuel_main_in_assisted_mode
                
                if current_total_fuel_assisted < main_only_inefficient_candidate_fuel:
                    # Orijinal koddaki gibi etiketleme ve yük bilgisi oluşturma
                    loads_info_for_assisted_option = []
                    label_parts_assisted = []
                    if port_gen_power_output > 1e-3:
                        loads_info_for_assisted_option.append((port_mcr, target_port_load_percentage, "Liman"))
                        label_parts_assisted.append(f"1x{port_mcr}kW Liman ({target_port_load_percentage:.1f}%)")
                    if total_fuel_main_in_assisted_mode > 0:
                        for _ in range(n_main_assisted):
                            loads_info_for_assisted_option.append((main_mcr, current_main_gens_load_percentage, "Ana"))
                        label_parts_assisted.insert(0, f"{n_main_assisted}x{main_mcr}kW Ana ({current_main_gens_load_percentage:.1f}%)")
                    
                    if not loads_info_for_assisted_option: continue
                    final_label_assisted = " + ".join(label_parts_assisted)
                    add_option("assisted_optimal", current_total_fuel_assisted, final_label_assisted, loads_info_for_assisted_option, original_main_info_for_assisted)

    # --- KARAR VERME MANTIĞI ---
    final_choice_key = None
    preferred_keys_order = ["main_eff", "main_eff_plus_one", "assisted_optimal", "port_only"]
    current_best_fuel = float('inf')
    
    for p_key in preferred_keys_order:
        if p_key in evaluated_options:
            candidate_fuel = evaluated_options[p_key][0]
            if candidate_fuel < current_best_fuel:
                current_best_fuel = candidate_fuel
                final_choice_key = p_key

    if final_choice_key is None and evaluated_options:
        sorted_by_fuel = sorted(evaluated_options.items(), key=lambda item: item[1][0])
        if sorted_by_fuel:
            final_choice_key = sorted_by_fuel[0][0]

    if final_choice_key:
        fuel, label, loads, original_info = evaluated_options[final_choice_key]
        if original_info:
            is_assisted = original_info[2]
        else:
            is_assisted = ("assisted" in final_choice_key)
        
        final_original_info = (original_info[0] if original_info else None, 
                               original_info[1] if original_info else None, 
                               is_assisted)
        
        return fuel, label, loads, final_original_info

    else:
        return 0.0, "Uygun Kombinasyon Yok", [], (None, None, False)
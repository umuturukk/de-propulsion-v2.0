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
    loads = list(sfoc_data_input.keys())
    sfocs = list(sfoc_data_input.values())

    # İnterpolasyon için yük ve SFOC değerlerini sırala
    sorted_indices = np.argsort(loads)
    sorted_loads = np.array(loads)[sorted_indices]
    sorted_sfocs = np.array(sfocs)[sorted_indices]

    # İnterpolasyon için en az 2 nokta olmalı
    if len(sorted_loads) < 2:
        # st.warning("SFOC interpolasyonu için yeterli veri noktası yok.") # UI elemanı burada olmamalı
        return None

    try:
        # Karesel (quadratic) interpolasyon, fill_value="extrapolate" ile aralık dışı değerler için ekstrapolasyon yapar
        interp_func = interp1d(sorted_loads, sorted_sfocs, kind='quadratic', fill_value="extrapolate")
        sfoc_value = float(interp_func(load_percentage))

        # SFOC için alt sınır kontrolü (calculate_fuel içinde de var)
        # if sfoc_value < 50 and load_percentage > 0: # 0 yük hariç
        #     pass # Kontrol calculate_fuel içinde daha detaylı
        return sfoc_value
    except ValueError as e:
        # print(f"SFOC İnterpolasyon Hatası: {e} (Yük: {load_percentage})") # Hata loglama
        return None

def calculate_fuel(power_output_kw, load_percent_on_engine, duration_hr, sfoc_data_input):
    """
    Verilen parametreler için yakıt tüketimini ton olarak hesaplar.
    """
    if power_output_kw <= 0 or duration_hr <= 0:
        return 0.0

    sfoc = interpolate_sfoc_non_linear(load_percent_on_engine, sfoc_data_input)

    # SFOC değeri makul değilse veya hesaplanamadıysa yakıt tüketimini 0 kabul et
    if sfoc is None or sfoc < 50:  # 50 g/kWh SFOC için makul olmayan bir alt sınır
        return 0.0 # Veya None döndürülerek hata belirtilebilir
    
    # Yakıt Tüketimi (ton) = (Güç (kW) * Süre (saat) * SFOC (g/kWh)) / 1,000,000 (g'ı tona çevirmek için)
    return (power_output_kw * duration_hr * sfoc) / 1_000_000

# --- Güç Akış Diyagramı için Hesaplamalar ("Yakıt Analizi" sayfası) ---
def calculate_power_flow(shaft_power, motor_eff, converter_eff, switchboard_eff, generator_alternator_eff):
    """
    Güç akış diyagramı için güç değerlerini ve kayıpları hesaplar.
    generator_alternator_eff: Alternatörün kendi elektriksel verimliliği.
    """
    if shaft_power <= 0:
        return None, None
    if not all([motor_eff > 0, converter_eff > 0, switchboard_eff > 0, generator_alternator_eff > 0]):
        return None, None

    p_shaft = shaft_power                                      # Pervane Şaft Gücü (Mekanik Çıkış)
    p_motor_input = p_shaft / motor_eff                        # Elektrik Motoru Giriş Gücü (Elektriksel)
    p_converter_input = p_motor_input / converter_eff          # Frekans Konvertörü Giriş Gücü (Elektriksel)
    # Ana Panodan Konvertöre Giden Güç (p_converter_input ile aynı olmalı, pano kaybı burada değil, jeneratörden panoya olan kısımda)
    # Orijinal kod: p_switchboard_in = p_converter_in / switchboard_eff
    # Bu p_switchboard_in, panonun *girişindeki* güç (jeneratörlerden gelen).
    # Yani, p_converter_input = p_switchboard_output
    # p_switchboard_output = p_switchboard_input * switchboard_eff
    # Dolayısıyla, p_switchboard_input (jeneratörlerden panoya) = p_converter_input / switchboard_eff
    p_switchboard_input_from_gens = p_converter_input / switchboard_eff # Jeneratörlerden panoya gelen güç

    # Alternatörlerin üretmesi gereken toplam elektriksel güç (p_switchboard_input_from_gens ile aynı)
    p_alternator_elec_output = p_switchboard_input_from_gens
    # Alternatörlerin bu elektriksel gücü üretmek için ihtiyaç duyduğu mekanik güç
    p_alternator_mech_input = p_alternator_elec_output / generator_alternator_eff

    if any([not np.isfinite(val) for val in [p_motor_input, p_converter_input, p_switchboard_input_from_gens, p_alternator_mech_input]]):
        return None, None

    loss_motor = p_motor_input - p_shaft
    loss_converter = p_converter_input - p_motor_input
    loss_switchboard = p_switchboard_input_from_gens - p_converter_input # Pano içi kayıp
    loss_alternator = p_alternator_mech_input - p_alternator_elec_output   # Alternatör içi kayıp

    power_values = {
        "shaft": p_shaft,                                 # Şafta iletilen mekanik güç
        "motor_input": p_motor_input,                     # Motora giren elektrik gücü
        "converter_input": p_converter_input,             # Konvertöre giren elektrik gücü
        "switchboard_input_from_gens": p_switchboard_input_from_gens, # Panoya jeneratörlerden gelen elektrik gücü
        "alternator_elec_output": p_alternator_elec_output, # Alternatörlerin toplam elektrik çıkışı (panoya giden)
        "alternator_mech_input": p_alternator_mech_input   # Alternatörlere dizel motorlardan gelen mekanik güç
    }
    loss_values = {
        "motor": loss_motor,
        "converter": loss_converter,
        "switchboard": loss_switchboard,
        "alternator": loss_alternator
    }
    return power_values, loss_values

# --- "Yeni Jeneratör Kombinasyonları" sayfası için Yardımcı Fonksiyonlar ---
def find_min_gens_for_power(required_power, unit_mcr, unit_qty):
    """
    Belirli bir güç ihtiyacını karşılamak için gereken minimum jeneratör sayısını bulur.
    (Belirli bir tip jeneratör için)
    """
    if unit_mcr <= 0 or unit_qty <= 0:
        return None # Jeneratör MCR veya adedi geçersiz
    if required_power <= 0:
        return 0 # Güç ihtiyacı yoksa 0 jeneratör

    min_gens = np.ceil(required_power / unit_mcr)
    return int(min_gens) if min_gens <= unit_qty else None # Adet yeterliyse döndür

def evaluate_combination(required_de_power, running_gens_info, sfoc_data, duration):
    """
    Belirli bir çalışan jeneratör kombinasyonunun toplam yakıt tüketimini ve yüklerini değerlendirir.
    running_gens_info: [(mcr1, type1), (mcr2, type2), ...] formatında liste.
    """
    if not running_gens_info:
        return None

    # Çalışan jeneratörlerin MCR'ları ve toplam kapasiteleri
    running_mcrs = [mcr for mcr, gen_type in running_gens_info]
    total_running_capacity = sum(running_mcrs)

    if total_running_capacity <= 0 or required_de_power <= 0:
        return None
    
    # İhtiyaç duyulan güç, çalışan kapasiteyi çok az aşabilir (tolerans)
    if required_de_power > total_running_capacity * 1.001: # %0.1 tolerans
        return None # Kapasite yetersiz

    # Güç dağılımı: Her jeneratör kapasitesiyle orantılı olarak yüklenir
    power_per_gen_list = []
    if total_running_capacity > 0:
        power_per_gen_list = [(required_de_power * gen_mcr / total_running_capacity) for gen_mcr in running_mcrs]
    else: # total_running_capacity = 0 ise (ama yukarıda kontrol edildi)
        power_per_gen_list = [0 for _ in running_mcrs]

    load_percent_list = [(power / mcr * 100) if mcr > 0 else 0 for power, mcr in zip(power_per_gen_list, running_mcrs)]

    total_fuel_for_combination = 0
    loads_info_for_combination = [] # [(mcr, load_%, type), ...]
    valid_fuel_calculations = 0

    for i in range(len(running_gens_info)):
        gen_mcr, gen_type_label = running_gens_info[i]
        load_percentage_on_gen = load_percent_list[i]
        power_output_of_gen = power_per_gen_list[i]

        # Aşırı yüklenme durumu (SFOC eğrisi genellikle %110'a kadar tanımlıdır)
        if load_percentage_on_gen > 110: # %110 yük sınırı
            continue # Bu jeneratör bu yükte çalışamaz, kombinasyon geçersiz olabilir

        fuel_part = calculate_fuel(power_output_of_gen, load_percentage_on_gen, duration, sfoc_data)

        if fuel_part is not None and fuel_part > 0:
            total_fuel_for_combination += fuel_part
            loads_info_for_combination.append((gen_mcr, load_percentage_on_gen, gen_type_label))
            valid_fuel_calculations += 1
        elif power_output_of_gen > 0: # Güç çekiliyorsa ama yakıt hesaplanamadıysa sorun var
             # Bu durum, kombinasyonun geçersiz olduğu anlamına gelebilir.
             # Şimdilik sadece yakıtı pozitif olanları sayıyoruz.
             pass


    # Eğer en az bir jeneratörden geçerli yakıt hesaplandıysa ve toplam yakıt pozitifse
    if valid_fuel_calculations > 0 and total_fuel_for_combination > 0:
        # Eğer çalışan jeneratör sayısı ile geçerli yakıt hesaplanan jeneratör sayısı uyuşmuyorsa
        # (örn. bir jeneratör aşırı yüklendiği için atlandıysa), bu kombinasyon tam olarak isteneni karşılamıyor olabilir.
        # Orijinal mantıkta bu kontrol yoktu, sadece pozitif yakıt varsa devam ediyordu.
        # Şimdilik orijinal mantığı koruyalım:
        return total_fuel_for_combination, loads_info_for_combination
    else:
        return None


def get_best_combination(required_de_power, main_mcr, main_qty, port_mcr, port_qty, sfoc_data, duration):
    """
    Verilen güç ihtiyacı için en iyi (en az yakıt tüketen) jeneratör kombinasyonunu bulur.
    """
    if required_de_power <= 0:
        return 0.0, "0 kW Yük (Yakıt Yok)", [], (None, None, False) # (fuel, label, loads, original_main_info)

    evaluated_options = {} # Key: option_type, Value: (fuel, label, loads_info, original_main_details_tuple)

    def add_option(key, fuel, label, loads, original_info_tuple=None):
        # Daha düşük yakıt tüketimine sahip olanı veya ilk bulunanı sakla
        if key not in evaluated_options or fuel < evaluated_options[key][0]:
            evaluated_options[key] = (fuel, label, loads, original_info_tuple)

    # Sadece ana jeneratörlerin verimsiz çalıştığı durum için referans
    main_only_inefficient_candidate_fuel = None
    main_only_inefficient_candidate_label = None
    main_only_inefficient_candidate_loads = None # [(mcr, load, type), ...]
    # original_main_loads_for_inefficient_case = [] # Bu değişkene gerek kalmadı

    # --- STRATEJİ 1: SADECE ANA JENERATÖRLER ---
    if main_qty > 0 and main_mcr > 0:
        n_main1 = find_min_gens_for_power(required_de_power, main_mcr, main_qty)
        if n_main1 is not None: # Yeterli sayıda ana jeneratör varsa
            running_info1 = [(main_mcr, "Ana")] * n_main1
            eval_res1 = evaluate_combination(required_de_power, running_info1, sfoc_data, duration)
            if eval_res1:
                fuel1, loads1 = eval_res1
                label1 = f"{n_main1}x {main_mcr}kW Ana"
                # Yük yüzdesi, çalışan ilk ana jeneratörün yükü olarak alınabilir (hepsi eşit yüklenecek)
                load_pct1 = loads1[0][1] if loads1 else 100.0 # loads1 boş değilse ilk elemanın yükü

                if 65 <= load_pct1 <= 92: # Verimli çalışma aralığı
                    add_option("main_eff", fuel1, label1, loads1)
                elif load_pct1 < 65: # Verimsiz düşük yük
                    main_only_inefficient_candidate_fuel = fuel1
                    main_only_inefficient_candidate_label = label1
                    main_only_inefficient_candidate_loads = loads1
                    add_option("main_ineff_low", fuel1, label1, loads1) # Düşük verimli olarak kaydet
                elif load_pct1 > 92 and n_main1 + 1 <= main_qty: # Aşırı yük ve bir fazla jeneratör denenebilir
                    n_main2 = n_main1 + 1
                    if n_main2 * main_mcr >= required_de_power: # Eklenen jeneratörle kapasite yeterli mi?
                        running_info2 = [(main_mcr, "Ana")] * n_main2
                        eval_res2 = evaluate_combination(required_de_power, running_info2, sfoc_data, duration)
                        if eval_res2:
                            fuel2, loads2 = eval_res2
                            label2 = f"{n_main2}x {main_mcr}kW Ana"
                            load_pct2 = loads2[0][1] if loads2 else 100.0
                            if 65 <= load_pct2 <= 92: # Bir fazla jeneratörle verimli aralık
                                add_option("main_eff_plus_one", fuel2, label2, loads2)
                            elif load_pct2 < 65: # Bir fazla jeneratörle hala düşük yük (ama belki daha iyi SFOC)
                                # Bu durumu da inefficient candidate olarak değerlendir, eğer öncekinden iyiyse
                                if main_only_inefficient_candidate_fuel is None or fuel2 < main_only_inefficient_candidate_fuel:
                                    main_only_inefficient_candidate_fuel = fuel2
                                    main_only_inefficient_candidate_label = label2
                                    main_only_inefficient_candidate_loads = loads2
                                add_option("main_ineff_low_plus_one", fuel2, label2, loads2)
                            else: # Diğer durumlar (örn: %92 üzeri ama < %110)
                                add_option("main_fallback_plus_one", fuel2, label2, loads2)
                else: # n_main1 zaten maksimumda ve yük > %92 veya diğer durumlar
                    add_option("main_fallback_at_n_main1", fuel1, label1, loads1) # Fallback olarak ekle

    # --- STRATEJİ 2: SADECE LİMAN JENERATÖR(LER)İ ---
    if port_qty > 0 and port_mcr > 0:
        n_port = find_min_gens_for_power(required_de_power, port_mcr, port_qty)
        if n_port is not None and n_port > 0: # Liman jeneratörü adedi 0 olmamalı
            running_info_port = [(port_mcr, "Liman")] * n_port
            eval_res_port = evaluate_combination(required_de_power, running_info_port, sfoc_data, duration)
            if eval_res_port:
                fuel_p, loads_p = eval_res_port
                label_p = f"{n_port}x {port_mcr}kW Liman"
                add_option("port_only", fuel_p, label_p, loads_p)

    # --- STRATEJİ 3: DESTEKLİ MOD (1 Liman Jen + N Ana Jen) ---
    # Bu strateji, sadece ana jeneratörlerin verimsiz (örn. <%65 yük) çalıştığı bir durum varsa denenir.
    if main_only_inefficient_candidate_fuel is not None and port_qty >= 1 and port_mcr > 0 and main_qty >= 1:
        num_main_in_inefficient_case = 0
        if main_only_inefficient_candidate_loads:
            num_main_in_inefficient_case = sum(1 for _m, _l, gen_type in main_only_inefficient_candidate_loads if gen_type == "Ana")

        # Denenecek ana jeneratör sayıları:
        # 1. Verimsiz durumdakinden bir eksik (eğer >1 ise)
        # 2. Her zaman 1 ana jeneratör
        # 3. Verimsiz durumdaki ana jeneratör sayısı
        n_main_options_for_assisted = []
        if num_main_in_inefficient_case > 1:
            n_main_options_for_assisted.append(num_main_in_inefficient_case - 1)
        if 1 not in n_main_options_for_assisted and main_qty >= 1 : # En az 1 ana jen varsa ve listede yoksa ekle
             n_main_options_for_assisted.append(1)
        if num_main_in_inefficient_case > 0 and num_main_in_inefficient_case not in n_main_options_for_assisted:
            n_main_options_for_assisted.append(num_main_in_inefficient_case)
        
        # Oluşan seçenekleri filtrele (0'dan büyük ve mevcut ana jen sayısından az/eşit) ve sırala
        n_main_options_for_assisted = sorted(list(set(n for n in n_main_options_for_assisted if 0 < n <= main_qty)))

        # Eğer yukarıdaki mantıkla hiç seçenek oluşmazsa ve ana jeneratör varsa, en az 1 ile denemeyi ekle
        if not n_main_options_for_assisted and main_qty > 0:
            n_main_options_for_assisted.append(1)
        
        original_main_info_for_assisted = (main_only_inefficient_candidate_fuel, main_only_inefficient_candidate_label, True)


        for n_main_assisted in n_main_options_for_assisted:
            # Liman jeneratörü yükünü %85'ten %60'a doğru belirli adımlarla dene
            for target_port_load_percentage in range(85, 59, -5): # 85, 80, ..., 65, 60
                port_gen_power_output = port_mcr * (target_port_load_percentage / 100.0)

                # Liman jeneratörü tek başına gücü karşılıyorsa veya aşıyorsa
                if port_gen_power_output >= required_de_power - 1e-3: # Küçük tolerans
                    if n_main_assisted > 0: continue # Ana jeneratöre gerek kalmadı, bu kombinasyon geçerli değil
                    remaining_power_for_main_gens = 0 # Ana jeneratörler çalışmayacak
                else:
                    remaining_power_for_main_gens = required_de_power - port_gen_power_output

                current_main_gens_power_output_per_gen = 0
                current_main_gens_load_percentage = 0

                if n_main_assisted > 0: # Ana jeneratörler çalışacaksa
                    if remaining_power_for_main_gens <= 1e-3: # Ana jeneratörler için çok az/negatif yük
                        continue
                    # Ana jeneratörlerin kapasitesi kalan gücü karşılamaya yeterli mi?
                    if n_main_assisted * main_mcr < remaining_power_for_main_gens - 1e-3:
                        continue # Kapasite yetersiz
                    
                    current_main_gens_power_output_per_gen = remaining_power_for_main_gens / n_main_assisted
                    current_main_gens_load_percentage = (current_main_gens_power_output_per_gen / main_mcr) * 100
                    
                    # Ana jeneratör yük kontrolü (çok önemli)
                    if not (5.0 <= current_main_gens_load_percentage <= 92.0 + 1e-9): # %5-%92 aralığı
                        # print(f"DEBUG Assisted: Main load {current_main_gens_load_percentage:.1f}% out of range for Nmain={n_main_assisted}, DE={required_de_power:.0f}, PortP={port_gen_power_output:.0f}")
                        continue
                elif remaining_power_for_main_gens > 1e-3 : # Ana jen. yok ama hala güç ihtiyacı var
                    continue


                # Yakıt Hesaplaması
                # Liman jeneratörü yakıtı
                fuel_port_in_assisted_mode = calculate_fuel(port_gen_power_output, target_port_load_percentage, duration, sfoc_data)
                if fuel_port_in_assisted_mode is None or (fuel_port_in_assisted_mode <= 0 and port_gen_power_output > 1e-3):
                    continue # Liman jeneratörü yakıtı hesaplanamadı veya geçersiz

                # Ana jeneratörler yakıtı
                total_fuel_main_in_assisted_mode = 0
                if n_main_assisted > 0 and current_main_gens_power_output_per_gen > 1e-3:
                    fuel_main_part = calculate_fuel(current_main_gens_power_output_per_gen, current_main_gens_load_percentage, duration, sfoc_data)
                    if fuel_main_part is None or (fuel_main_part <= 0 and current_main_gens_power_output_per_gen > 1e-3):
                        # print(f"DEBUG Assisted: Main fuel calc failed. Partfuel={fuel_main_part} for load {current_main_gens_load_percentage}")
                        continue # Bir ana jeneratörün yakıtı hesaplanamadı
                    total_fuel_main_in_assisted_mode = fuel_main_part * n_main_assisted
                
                current_total_fuel_assisted = (fuel_port_in_assisted_mode if fuel_port_in_assisted_mode else 0) + total_fuel_main_in_assisted_mode

                # Koşul Kontrolleri:
                # 1. Liman jeneratörü %60-%85 aralığında olmalı. (Zaten döngüde bu aralıkta)
                # 2. Ana jeneratörler (eğer çalışıyorsa) %65-%90 (ideal) veya %90-%92 (kabul edilebilir) aralığında olmalı.
                #    Veya ana jeneratör yükü, "sadece ana jen. verimsiz" durumuna göre iyileşmiş olmalı.
                
                main_gen_load_ok_for_assisted = False
                if n_main_assisted == 0: # Sadece liman jeneratörü çalışıyor
                    main_gen_load_ok_for_assisted = True
                elif current_main_gens_power_output_per_gen <= 1e-3: # Ana jen. var ama yükü yok
                    main_gen_load_ok_for_assisted = True
                else: # Ana jeneratörler yük altında
                    if 65.0 <= current_main_gens_load_percentage <= 90.0: # İdeal aralık
                        main_gen_load_ok_for_assisted = True
                    elif 90.0 < current_main_gens_load_percentage <= (92.0 + 1e-9): # Kabul edilebilir üst aralık
                        # Bu durumda, sadece ana jeneratörlerin verimsiz çalıştığı duruma göre bir iyileşme varsa kabul et
                        if main_only_inefficient_candidate_loads and main_only_inefficient_candidate_fuel is not None:
                            # Ortalama eski ana jen yükü (eğer varsa)
                            avg_original_main_load = 0
                            count_original_main = 0
                            if main_only_inefficient_candidate_loads:
                                for _m, _l, _t in main_only_inefficient_candidate_loads:
                                    if _t == "Ana": avg_original_main_load += _l; count_original_main +=1
                                if count_original_main > 0: avg_original_main_load /= count_original_main
                                else: avg_original_main_load = 101 # Karşılaştırma için yüksek bir değer

                            # Yeni yük yüzdesi eskisinden daha iyiyse (daha yüksek ve verimliye yakınsa) VEYA daha az ana jeneratör kullanılıyorsa
                            if current_main_gens_load_percentage > avg_original_main_load or n_main_assisted < count_original_main :
                                main_gen_load_ok_for_assisted = True
                        # else: Eğer karşılaştırılacak durum yoksa veya iyileşme sağlamıyorsa bu aralığı (%90-%92) tek başına tercih etme.

                # Bu destekli mod seçeneği eklenebilir mi?
                # 1. Yükler uygun aralıklarda olmalı.
                # 2. Toplam yakıt, "sadece ana jen. verimsiz" durumundan daha iyi olmalı.
                if main_gen_load_ok_for_assisted and current_total_fuel_assisted < main_only_inefficient_candidate_fuel:
                    loads_info_for_assisted_option = []
                    label_parts_assisted = []

                    if port_gen_power_output > 1e-3:
                        loads_info_for_assisted_option.append((port_mcr, target_port_load_percentage, "Liman"))
                        label_parts_assisted.append(f"1x{port_mcr}kW Liman ({target_port_load_percentage:.1f}%)")
                    
                    if n_main_assisted > 0 and current_main_gens_power_output_per_gen > 1e-3:
                        for _ in range(n_main_assisted): # Her bir ana jeneratör için ayrı kayıt
                            loads_info_for_assisted_option.append((main_mcr, current_main_gens_load_percentage, "Ana"))
                        # Etikette sadece bir kere belirt
                        label_parts_assisted.insert(0, f"{n_main_assisted}x{main_mcr}kW Ana ({current_main_gens_load_percentage:.1f}%)")
                    
                    if not loads_info_for_assisted_option: continue # Hiçbir jeneratör çalışmıyorsa atla

                    final_label_assisted = " + ".join(label_parts_assisted) if label_parts_assisted else "Tanımsız Destekli Mod"
                    add_option("assisted_optimal", current_total_fuel_assisted, final_label_assisted, loads_info_for_assisted_option, original_main_info_for_assisted)
                    # Bu n_main_assisted için iyi bir opsiyon bulundu, liman yükü döngüsünden çıkabilir.
                    # VEYA en iyi liman yükünü bulmak için devam etmeli. add_option zaten en iyiyi tutuyor.
                    # break # Şimdilik ilk bulunan iyi opsiyonda duralım. (Yüksek liman yükü öncelikli)

    # --- KARAR VERME MANTIĞI ---
    final_choice_key = None
    # Öncelik sırası: En verimli ana jen > Bir fazla ana jen (verimli) > Destekli Mod (verimli) > Sadece Liman Jen.
    preferred_keys_order = ["main_eff", "main_eff_plus_one", "assisted_optimal", "port_only"]
    
    current_best_fuel = float('inf')
    for p_key in preferred_keys_order:
        if p_key in evaluated_options:
            candidate_fuel = evaluated_options[p_key][0]
            # Sadece daha iyi bir seçenek bulunursa güncelle
            if candidate_fuel < current_best_fuel:
                current_best_fuel = candidate_fuel
                final_choice_key = p_key

    # Eğer yukarıdaki öncelikli kurallarla bir şey seçilemediyse (örn. hiçbiri yoktu veya hepsi çok kötüydü),
    # tüm geçerli opsiyonlar arasından en düşük yakıtlıyı seç (fallback).
    if final_choice_key is None and evaluated_options:
        # En düşük yakıt tüketimine sahip olanı bul
        # evaluated_options.items() -> [(key, (fuel, label, loads, orig_info)), ...]
        sorted_by_fuel = sorted(evaluated_options.items(), key=lambda item: item[1][0])
        if sorted_by_fuel:
            final_choice_key = sorted_by_fuel[0][0] # En düşük yakıtlı olanın key'i

    if final_choice_key:
        fuel, label, loads, original_info = evaluated_options[final_choice_key]
        # original_info'nun (fuel, label, is_assisted_flag) formatında olduğundan emin ol
        if original_info:
            if len(original_info) == 2: # Eski format (sadece fuel, label)
                return fuel, label, loads, (original_info[0], original_info[1], (final_choice_key == "assisted_optimal"))
            # Eğer len(original_info) == 3 ise zaten doğru formatta
        else: # original_info yoksa (örn. assisted olmayan birincil seçenek)
             original_info = (None, None, (final_choice_key == "assisted_optimal")) # is_assisted durumunu yine de ayarla

        return fuel, label, loads, original_info

    else: # Hiçbir uygun kombinasyon bulunamadı
        return 0.0, "Uygun Kombinasyon Yok", [], (None, None, False)
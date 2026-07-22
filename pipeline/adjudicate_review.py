#!/usr/bin/env python3
"""Adjudicate review cases from affiliation-map.csv.

Reads all status=review rows, applies corrections, sets status=manual.
"""

import csv
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
INST_DB = os.path.join(REPO_ROOT, "data", "institutions.json")

MAP_FIELDS = [
    "raw_affiliation", "status", "institution_id", "institution_name",
    "institution_type", "country_code", "lineage", "score", "matched_via", "candidate",
]


def load_inst_db():
    with open(INST_DB) as f:
        return json.load(f)


def load_map():
    rows = {}
    with open(MAP_CSV, newline="") as f:
        for r in csv.DictReader(f):
            rows[r["raw_affiliation"]] = r
    return rows


def save_map(rows):
    os.makedirs(os.path.dirname(MAP_CSV), exist_ok=True)
    with open(MAP_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAP_FIELDS)
        w.writeheader()
        for raw in sorted(rows):
            row = {k: rows[raw].get(k, "") for k in MAP_FIELDS}
            w.writerow(row)


def find_inst(db, name=None, id=None):
    """Find institution by name or ID."""
    by_id = db["by_id"]
    by_name = db["by_name"]
    
    if id:
        return by_id.get(id)
    
    if name:
        key = name.lower().strip()
        if key in by_name:
            return by_id.get(by_name[key])
    return None


def main():
    db = load_inst_db()
    mapping = load_map()
    
    # Corrections dictionary
    # Format: raw_affiliation -> (institution_id, institution_name, institution_type, country_code)
    corrections = {
        # === COMPANIES (unmatched - not education) ===
        # Synopsys
        "Synopsys": ("", "", "company", ""),
        "Synopsys Inc": ("", "", "company", ""),
        "Synopsys Inc.": ("", "", "company", ""),
        "Synopsys Inc.,": ("", "", "company", ""),
        "Synopsys,Inc.,Aachen,Germany": ("", "", "company", "DE"),
        "Synopsys, Inc": ("", "", "company", ""),
        "Synopsys, Inc.,": ("", "", "company", ""),
        "Synopsys, Inc.,Sunnyvale,CA,USA": ("", "", "company", "US"),
        "Synopsys, Inc., Sunnyvale, USA": ("", "", "company", "US"),
        "Synopsys, Inc.,Taipei,Taiwan": ("", "", "company", "TW"),
        "Synopsys, Inc,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Synopsys,Inc": ("", "", "company", ""),
        "Synopsys,Inc.,Aachen,Germany": ("", "", "company", "DE"),
        "Synopsys Inc.,Leuven,Belgium": ("", "", "company", "BE"),
        "Synopsys Inc.,Ottawa,Canada": ("", "", "company", "CA"),
        "Synopsys Inc.,Sunnyvale,CA,USA": ("", "", "company", "US"),
        "Synopsys Inc.,Sunnyvale,USA": ("", "", "company", "US"),
        "Synopsys,California,US": ("", "", "company", "US"),
        
        # Intel
        "Intel": ("", "", "company", ""),
        "Intel Corporation": ("", "", "company", ""),
        "Intel Corporation,": ("", "", "company", ""),
        "Intel Corporation,Compact Device Modeling Group, Design Enab": ("", "", "company", ""),
        "Intel Corporation,Components Research,Hillsboro,OR,USA": ("", "", "company", "US"),
        "Intel Corporation,Components Research,Hillsboro,OR,USA,97124": ("", "", "company", "US"),
        "Intel Corporation,Components Research,Hillsboro,OR,USA,97214": ("", "", "company", "US"),
        "Intel Corporation,Corporate Quality Network,Hillsboro,OR,USA": ("", "", "company", "US"),
        "Intel Corporation,Design Enablement,Hillsboro,OR,USA,97124": ("", "", "company", "US"),
        "Intel Corporation,Global Sourcing for Equipment and Material": ("", "", "company", ""),
        "Intel Corporation,Intel Labs,Hillsboro,Oregon": ("", "", "company", "US"),
        "Intel Corporation,Portland Technology Development,Hillsboro,": ("", "", "company", "US"),
        "Intel,Austin,TX,USA": ("", "", "company", "US"),
        "Intel,Chandler,AZ,USA": ("", "", "company", "US"),
        "Intel,Hillsboro,OR,USA": ("", "", "company", "US"),
        "Intel,Portland,OR,USA": ("", "", "company", "US"),
        
        # NVIDIA
        "NVIDIA": ("", "", "company", ""),
        "NVIDIA Corp.": ("", "", "company", ""),
        "NVIDIA Corporation": ("", "", "company", ""),
        "NVIDIA Research, Austin, USA": ("", "", "company", "US"),
        "NVIDIA, Austin, Texas, USA": ("", "", "company", "US"),
        "NVIDIA, Austin, USA": ("", "", "company", "US"),
        "NVIDIA,Austin,TX,US": ("", "", "company", "US"),
        "NVIDIA,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Nvidia": ("", "", "company", ""),
        "Nvidia Corporation": ("", "", "company", ""),
        "Nvidia Corporation, Austin, Texas, USA": ("", "", "company", "US"),
        "Nvidia,USA": ("", "", "company", "US"),
        "Research Nvidia,Austin,Texas,USA": ("", "", "company", "US"),
        "Research Nvidia,Hsinchu,Taiwan": ("", "", "company", "TW"),
        
        # Samsung
        "Samsung Advanced Institute of Technology,Machine Learning Te": ("", "", "company", "KR"),
        "Samsung Advanced Institute of Technology,Suwon,Korea": ("", "", "company", "KR"),
        "Samsung Advanced Institute of Technology,Suwon,South Korea": ("", "", "company", "KR"),
        "Samsung Electronics": ("", "", "company", "KR"),
        "Samsung Electronics Co., Ltd,Air Science Research Center, Sa": ("", "", "company", "KR"),
        "Samsung Electronics Co.,Memory Division,Suwon,Korea,18448": ("", "", "company", "KR"),
        "Samsung Electronics,Design AI Lab,Suwon,Rebublic of Korea": ("", "", "company", "KR"),
        "Samsung Electronics, Hwaseong, Gyeonggi, Republic of Korea": ("", "", "company", "KR"),
        "Samsung Electronics,Suwon,South Korea": ("", "", "company", "KR"),
        
        # MediaTek
        "MediaTek Inc": ("", "", "company", "TW"),
        "MediaTek Inc.,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Mediatek, Hsinchu, Taiwan": ("", "", "company", "TW"),
        
        # STMicroelectronics
        "STMicroelectronics": ("", "", "company", ""),
        "STMicroelectronics,Crolles,France": ("", "", "company", "FR"),
        "STMicroelectronics,Crolles,France,38926": ("", "", "company", "FR"),
        "STMicroelectronics, Digital FMT, Technology for Optical Sens": ("", "", "company", "FR"),
        "STMicroelectronics,Geneva,Switzerland": ("", "", "company", "CH"),
        
        # GlobalFoundries
        "GlobalFoundries": ("", "", "company", ""),
        "GlobalFoundries, Inc.,Malta,NY,12020": ("", "", "company", "US"),
        "GlobalFoundries,Dresden,Germany": ("", "", "company", "DE"),
        
        # AMD
        "AMD, Austin, TX, USA": ("", "", "company", "US"),
        
        # Cadence
        "Cadence Design System, Inc.,Austin,TX": ("", "", "company", "US"),
        
        # Google
        "Google": ("", "", "company", "US"),
        
        # Huawei (research lab, not education)
        "Huawei Technologies R&D,Leuven,Belgium": ("", "", "company", "BE"),
        "Noah's Ark Lab, Huawei": ("", "", "company", ""),
        "Noah's Ark Lab, Huawei, Shatin, Hong Kong": ("", "", "company", "HK"),
        "Noah's Ark Lab, Huawei, Shenzhen, China": ("", "", "company", "CN"),
        
        # Tencent
        "Tencent Quantum Lab, Shenzhen, Guangdong, China": ("", "", "company", "CN"),
        
        # Other companies
        "i4AI Ltd,London,United Kingdom,WCIN3AX": ("", "", "company", "GB"),
        "Infinigence-AI, Beijing, China": ("", "", "company", "CN"),
        "Infinigence-AI, Shanghai, China": ("", "", "company", "CN"),
        "Lightmatter,Boston,USA": ("", "", "company", "US"),
        "Nokia Bell Labs,Paris,France": ("", "", "company", "FR"),
        "OMNIVISION,Mechelen,Belgium": ("", "", "company", "BE"),
        "Pathfinding Co-Optimization Technology & Systems (PACTS) Ime": ("", "", "company", ""),
        "QuinStar Inc,Torrance,CA,USA": ("", "", "company", "US"),
        "Realtek Semiconductor": ("", "", "company", ""),
        "Realtek Semiconductor Corp,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Realtek Semiconductor,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Reconova Technologies Co., Ltd.,Xiamen,China": ("", "", "company", "CN"),
        "S2C Inc., Shenzhen, China": ("", "", "company", "CN"),
        "Siemens": ("", "", "company", ""),
        "SiMa,USA": ("", "", "company", "US"),
        "Soitec": ("", "", "company", ""),
        "Soitec,Bernin,France": ("", "", "company", "FR"),
        "Sony Semiconductor Solutions Corporation,Atsugi,Japan": ("", "", "company", "JP"),
        "Taiwan SemiconductorManufacturing Company,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Toyota Central R&D Labs., Inc,Nagakute,Japan": ("", "", "company", "JP"),
        "Trimsignal, Athens, Attiki, Greece": ("", "", "company", "GR"),
        "Truth Memory Corporation,Beijing,China": ("", "", "company", "CN"),
        "Univista Industrial Software Group,Shanghai,China": ("", "", "company", "CN"),
        "ZTE,State Key Lab of Mobile Network and Mobile Communication": ("", "", "company", "CN"),
        
        # === UNIVERSITIES (fix wrong matches) ===
        # University at Buffalo
        "University at Buffalo--SUNY, Buffalo, NY, USA": ("https://openalex.org/I1436622", "University at Buffalo", "education", "US"),
        
        # Texas A&M
        "Texas A&M University College Station,TX,USA": ("https://openalex.org/I108679558", "Texas A&M University", "education", "US"),
        
        # NC State
        "NC State University, Raleigh, USA": ("https://openalex.org/I1836802", "North Carolina State University", "education", "US"),
        
        # Chinese University of Hong Kong
        "The Chinese University of Hong Kong, HongKong, China": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shatin, Hong Kong": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shatin, Hong Kong SAR": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shatin, Hong Kong, Chin": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shenzhen": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shenzhen, Shenzhen, Chi": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shenzhen, Shenzhen, China": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Sha Tin, Hong Kong": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Sha Tin, Hong Kong SAR": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        
        # Hong Kong University of Science and Technology
        "The Hong Kong University of Science and Technology,Departmet": ("https://openalex.org/I139008271", "Hong Kong University of Science and Technology", "education", "HK"),
        "The Hong Kong University of Science and Technology, hongkong": ("https://openalex.org/I139008271", "Hong Kong University of Science and Technology", "education", "HK"),
        
        # Hong Kong Polytechnic
        "The Hong Kong Polytechnic University,Department of Applied P": ("https://openalex.org/I148952132", "Hong Kong Polytechnic University", "education", "HK"),
        
        # University of Hong Kong
        "The University of Hong Kong, hongkong, Hong Kong": ("https://openalex.org/I138006014", "University of Hong Kong", "education", "HK"),
        "The University of Hong Kong, hongkong, hongkong, Hong Kong": ("https://openalex.org/I138006014", "University of Hong Kong", "education", "HK"),
        
        # Australian National University
        "The Australian National University,Research School of Physic": ("https://openalex.org/I127085974", "Australian National University", "education", "AU"),
        
        # Tsinghua
        "Tsinghua Univ.,BNRist,Dept. Computer Science & Tech.,Beijing": ("https://openalex.org/I136262950", "Tsinghua University", "education", "CN"),
        
        # UC Berkeley
        "UC,Berkeley,CA,USA": ("https://openalex.org/I134323397", "University of California, Berkeley", "education", "US"),
        
        # UoB Bristol
        "UoB,Bristol,UK": ("https://openalex.org/I100640900", "University of Bristol", "education", "GB"),
        
        # Technical University of Munich
        "Techical University of Munich, Munich, Germany": ("https://openalex.org/I140557060", "Technical University of Munich", "education", "DE"),
        
        # National Technical University of Athens
        "National Technichal University of Athens, Athens, Greece": ("https://openalex.org/I107434878", "National Technical University of Athens", "education", "GR"),
        
        # Peking University
        "School of Integrated Circuits, Pecking University, Beijing,": ("https://openalex.org/I78648837", "Peking University", "education", "CN"),
        "School of Integrated Circuits Peking University,Beijing,Chin": ("https://openalex.org/I78648837", "Peking University", "education", "CN"),
        "Peking University Shenzhen Graduate School,Key Lab of Integr": ("https://openalex.org/I78648837", "Peking University", "education", "CN"),
        
        # Fudan
        "School of Microelectronics, Fudan Univerisity, Shanghai, Chi": ("https://openalex.org/I137521230", "Fudan University", "education", "CN"),
        "State Key Laboratory of Integrated Chips and Systems, Fudan": ("https://openalex.org/I137521230", "Fudan University", "education", "CN"),
        
        # University of Chinese Academy of Sciences
        "School of integrated circuit, University of Chinese Academic": ("https://openalex.org/I153430078", "University of Chinese Academy of Sciences", "education", "CN"),
        
        # China University of Petroleum
        "SSSLab, Dept. of CST, China University of Petroleum-Beijing,": ("https://openalex.org/I140491685", "China University of Petroleum", "education", "CN"),
        "Super Scientific Software Laboratory, China University of Pe": ("https://openalex.org/I140491685", "China University of Petroleum", "education", "CN"),
        
        # Taipei Tech
        "Taipei Tech,Taipei,Taiwan,R.O.C.": ("https://openalex.org/I111328349", "National Taipei University of Technology", "education", "TW"),
        
        # Politecnico di Milano
        "Politecnico di Milano and IUNET,Informazione e Bioingegneria": ("https://openalex.org/I105358227", "Politecnico di Milano", "education", "IT"),
        
        # Queen's University Belfast
        "Queen's University Belfast,Centre for Secure Information Tec": ("https://openalex.org/I144011827", "Queen's University Belfast", "education", "GB"),
        
        # University of Sheffield
        "SoMaS, The University of Sheffield, Sheffield, United Kingdo": ("https://openalex.org/I126089217", "University of Sheffield", "education", "GB"),
        
        # Grenoble
        "Univ. Grenoble Alpes": ("https://openalex.org/I153389851", "Université Grenoble Alpes", "education", "FR"),
        "Univ. Grenoble Alpes,CEA-List,France": ("https://openalex.org/I153389851", "Université Grenoble Alpes", "education", "FR"),
        "Univ. Grenoble Alpes,CEA-Leti,Grenoble,France,F-38000": ("https://openalex.org/I153389851", "Université Grenoble Alpes", "education", "FR"),
        "Univ. Grenoble Alpes,CEA-Leti,France": ("https://openalex.org/I153389851", "Université Grenoble Alpes", "education", "FR"),
        "Univ. Grenoble Alpes,CEA-LETI,France": ("https://openalex.org/I153389851", "Université Grenoble Alpes", "education", "FR"),
        "Univ. Grenoble Alpes,CEA-Irig,Grenoble,France,F-38000": ("https://openalex.org/I153389851", "Université Grenoble Alpes", "education", "FR"),
        "Univ. Grenoble Alpes,CNRS Néel Institute,Grenoble,France,F-3": ("https://openalex.org/I153389851", "Université Grenoble Alpes", "education", "FR"),
        "Univ. Grenoble Alpes,Siquance,Grenoble,France,F-38000": ("https://openalex.org/I153389851", "Université Grenoble Alpes", "education", "FR"),
        
        # EPFL
        "EPFL–Ecole Polytechnique Fédérale de Lausanne,Institute of M": ("https://openalex.org/I13326684", "École Polytechnique Fédérale de Lausanne", "education", "CH"),
        
        # Ghent University
        "Ghent University-Imec,Photonics Research Group,INTEC Departm": ("https://openalex.org/I144955662", "Ghent University", "education", "BE"),
        
        # TU Dresden
        "NaMLab gGmbH/TU Dresden,Dresden,Germany": ("https://openalex.org/I118005644", "Technische Universität Dresden", "education", "DE"),
        
        # Technische Universität Dresden (already correct)
        "GlobalFoundries,Dresden,Germany": ("https://openalex.org/I118005644", "Technische Universität Dresden", "education", "DE"),
        "Fraunhofer IPMS - Center Nanoelectronics Technologies,Dresde": ("https://openalex.org/I118005644", "Technische Universität Dresden", "education", "DE"),
        
        # Reutlingen University
        "Bosch Mobility Electronics,Reutlingen,Germany": ("https://openalex.org/I132823654", "Reutlingen University", "education", "DE"),
        
        # IMEC (research institute, but education-adjacent)
        "Imec Vzw,Leuven,Belgium,B-3001": ("https://openalex.org/I120873516", "IMEC", "education", "BE"),
        "Institute of Microelectronics of the Chinese Academy of Scie": ("https://openalex.org/I6281385", "Institute of Microelectronics, Chinese Academy of Sciences", "education", "CN"),
        "Institute of Microelectronics of Chinese Academy of Sciences": ("https://openalex.org/I6281385", "Institute of Microelectronics, Chinese Academy of Sciences", "education", "CN"),
        
        # CEA-Leti (research institute, but education-adjacent)
        "CEA-Leti Minatec,Grenoble,France": ("https://openalex.org/I2005483", "CEA-Leti", "education", "FR"),
        
        # HKUST (fix for Kowloon Hospital mismatch)
        "The Hong Kong University of Science and Technology,Departmet": ("https://openalex.org/I139008271", "Hong Kong University of Science and Technology", "education", "HK"),
        "The Hong Kong University of Science and Technology, hongkong": ("https://openalex.org/I139008271", "Hong Kong University of Science and Technology", "education", "HK"),
        
        # CUHK Shenzhen (fix for Shenzhen Planck Innovation mismatch)
        "The Chinese University of Hong Kong,Shenzhen": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shenzhen, Shenzhen, Chi": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shenzhen, Shenzhen, China": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        
        # Zhejiang Gongshang (fix for Hangzhou mismatch)
        "the Key Laboratory of CS&AUS of Zhejiang Province, Hangzhou,": ("https://openalex.org/I2365876", "Zhejiang Gongshang University", "education", "CN"),
        "Nano Core Chip Electronic Technology,Hangzhou,China": ("https://openalex.org/I2365876", "Zhejiang Gongshang University", "education", "CN"),
        
        # IMEC (fix for IMECAS mismatch)
        "Institute of Microelectronics of the Chinese Academy of Scie": ("https://openalex.org/I6281385", "Institute of Microelectronics, Chinese Academy of Sciences", "education", "CN"),
        
        # Beijing institutions (fix for Beijing Geriatric Hospital mismatch)
        "Institute of Microelectronics of Chinese Academy of Sciences": ("https://openalex.org/I6281385", "Institute of Microelectronics, Chinese Academy of Sciences", "education", "CN"),
        "School of Integrated Circuits,Beijing,China": ("https://openalex.org/I6281385", "Institute of Microelectronics, Chinese Academy of Sciences", "education", "CN"),
        "School of Integrated Circuits Peking University,Beijing,Chin": ("https://openalex.org/I78648837", "Peking University", "education", "CN"),
        "School of Integrated Circuits, Pecking University, Beijing,": ("https://openalex.org/I78648837", "Peking University", "education", "CN"),
        "Semiconductor Technology Innovation Center (Beijing) Corpora": ("", "", "company", "CN"),
        "Sensetime Research, Beijing, China": ("", "", "company", "CN"),
        "State Key Laboratory of Integrated Chips and Systems (SKLICS": ("https://openalex.org/I137521230", "Fudan University", "education", "CN"),
        "Super Scientific Software Laboratory, China University of Pe": ("https://openalex.org/I140491685", "China University of Petroleum", "education", "CN"),
        "Tsinghua Univ.,BNRist,Dept. Computer Science & Tech.,Beijing": ("https://openalex.org/I136262950", "Tsinghua University", "education", "CN"),
        "Truth Memory Corporation,Beijing,China": ("", "", "company", "CN"),
        "Unaffiliated Scholar, Beijing, China": ("", "", "unmatched", ""),
        
        # Shanghai institutions (fix for Shanghai Institute mismatch)
        "School of Microelectronics, Fudan Univerisity, Shanghai, Chi": ("https://openalex.org/I137521230", "Fudan University", "education", "CN"),
        "Shanghai Huali Integrated Circuit Corporation,Shanghai,China": ("", "", "company", "CN"),
        "Shanghai Innovation Center for Processor Technologies, Shang": ("https://openalex.org/I137521230", "Fudan University", "education", "CN"),
        "Shanghai LEDA Technology Co., Ltd, Shanghai, China": ("", "", "company", "CN"),
        "Shanghai LEDA Technology Co., Ltd., Shanghai, China": ("", "", "company", "CN"),
        "State Key Laboratory of Integrated Chips and Systems, Fudan": ("https://openalex.org/I137521230", "Fudan University", "education", "CN"),
        "Zhangjiang Lab": ("https://openalex.org/I137521230", "Fudan University", "education", "CN"),
        "Zhangjiang Lab.,Shanghai,China": ("https://openalex.org/I137521230", "Fudan University", "education", "CN"),
        
        # Shenzhen institutions (fix for Shenzhen Planck Innovation mismatch)
        "Peking University Shenzhen Graduate School,Key Lab of Integr": ("https://openalex.org/I78648837", "Peking University", "education", "CN"),
        "S2C Inc., Shenzhen, China": ("", "", "company", "CN"),
        "Shenzhen Institute of Artificial Intelligence and Robotics f": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong,Shenzhen": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shenzhen, Shenzhen, Chi": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Shenzhen, Shenzhen, China": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        
        # Hsinchu institutions (fix for Hospital Santa Izabel mismatch)
        "Macronix International Co., Ltd": ("", "", "company", "TW"),
        "Macronix International Co., Ltd,Hsin-Chu,Taiwan, R.O.C.": ("", "", "company", "TW"),
        "Macronix International Co., Ltd,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Macronix International Co., Ltd.,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "NVIDIA,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Realtek Semiconductor": ("", "", "company", "TW"),
        "Realtek Semiconductor Corp,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Realtek Semiconductor,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Research Nvidia,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Taiwan SemiconductorManufacturing Company,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Taiwan Semiconductor Research Institute,Hsinchu,Taiwan": ("", "", "company", "TW"),
        
        # Austin institutions (fix for Aletheia University mismatch)
        "Intel,Austin,TX,USA": ("", "", "company", "US"),
        "NVIDIA Research, Austin, USA": ("", "", "company", "US"),
        "Research Nvidia,Austin,Texas,USA": ("", "", "company", "US"),
        
        # Grenoble institutions (fix for CEA Grenoble mismatch)
        "CEA-Leti Minatec,Grenoble,France": ("https://openalex.org/I2005483", "CEA-Leti", "education", "FR"),
        "CEA-Leti, Grenoble, France": ("https://openalex.org/I2005483", "CEA-Leti", "education", "FR"),
        "Hawai.tech,Grenoble,France": ("https://openalex.org/I153389851", "Université Grenoble Alpes", "education", "FR"),
        
        # Dresden institutions (fix for Dresden State Art Collections mismatch)
        "NaMLab gGmbH/TU Dresden,Dresden,Germany": ("https://openalex.org/I118005644", "Technische Universität Dresden", "education", "DE"),
        
        # Kowloon institutions (fix for Kowloon Hospital mismatch)
        "The Hong Kong Polytechnic University,Department of Applied P": ("https://openalex.org/I148952132", "Hong Kong Polytechnic University", "education", "HK"),
        
        # Shatin institutions (fix for Södertörn University mismatch)
        "The Chinese University of Hong Kong, Shatin, Hong Kong": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Sha Tin, Hong Kong": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        "The Chinese University of Hong Kong, Sha Tin, Hong Kong SAR": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        
        # Hong Kong institutions (fix for Home Office mismatch)
        "The Hong Kong University of Science and Technology, hongkong": ("https://openalex.org/I139008271", "Hong Kong University of Science and Technology", "education", "HK"),
        "The University of Hong Kong, hongkong, Hong Kong": ("https://openalex.org/I138006014", "University of Hong Kong", "education", "HK"),
        "The University of Hong Kong, hongkong, hongkong, Hong Kong": ("https://openalex.org/I138006014", "University of Hong Kong", "education", "HK"),
        
        # Beijing institutions (fix for Beijing Geriatric Hospital mismatch)
        "Institute of Microelectronics of Chinese Academy of Sciences": ("https://openalex.org/I6281385", "Institute of Microelectronics, Chinese Academy of Sciences", "education", "CN"),
        "School of Integrated Circuits,Beijing,China": ("https://openalex.org/I6281385", "Institute of Microelectronics, Chinese Academy of Sciences", "education", "CN"),
        "State Key Lab of Fabrication Technologies for Integrated Cir": ("https://openalex.org/I6281385", "Institute of Microelectronics, Chinese Academy of Sciences", "education", "CN"),
        
        # Suwon institutions (fix for Soran University mismatch)
        "Samsung Advanced Institute of Technology,Machine Learning Te": ("", "", "company", "KR"),
        "Samsung Advanced Institute of Technology,Suwon,Korea": ("", "", "company", "KR"),
        "Samsung Advanced Institute of Technology,Suwon,South Korea": ("", "", "company", "KR"),
        "Samsung Electronics": ("", "", "company", "KR"),
        "Samsung Electronics Co.,Memory Division,Suwon,Korea,18448": ("", "", "company", "KR"),
        "Samsung Electronics,Design AI Lab,Suwon,Rebublic of Korea": ("", "", "company", "KR"),
        "Samsung Electronics, Hwaseong, Gyeonggi, Republic of Korea": ("", "", "company", "KR"),
        "Samsung Electronics,Suwon,South Korea": ("", "", "company", "KR"),
        
        # Crolles institutions (fix for Centro di Riferimento Oncologico mismatch)
        "STMicroelectronics,Crolles,France": ("", "", "company", "FR"),
        "STMicroelectronics,Crolles,France,38926": ("", "", "company", "FR"),
        "STMicroelectronics, Digital FMT, Technology for Optical Sens": ("", "", "company", "FR"),
        
        # Geneva institutions (fix for General Electric mismatch)
        "STMicroelectronics,Geneva,Switzerland": ("", "", "company", "CH"),
        
        # Mechelen institutions (fix for Middle East College mismatch)
        "OMNIVISION,Mechelen,Belgium": ("", "", "company", "BE"),
        
        # Leuven institutions (fix for Universitair Ziekenhuis Leuven mismatch)
        "Imec Vzw,Leuven,Belgium,B-3001": ("https://openalex.org/I120873516", "IMEC", "education", "BE"),
        "Huawei Technologies R&D,Leuven,Belgium": ("", "", "company", "BE"),
        
        # Cambridge institutions (fix for Cambridge School mismatch)
        "ACX Instruments Ltd,Cambridge,United Kingdom": ("", "", "company", "GB"),
        "Dept. of EECS, MIT, Cambridge, United States": ("https://openalex.org/I137639241", "Massachusetts Institute of Technology", "education", "US"),
        "Dept. of EECS, MIT, Cambridge, USA": ("https://openalex.org/I137639241", "Massachusetts Institute of Technology", "education", "US"),
        
        # Trondheim institutions (fix for Rosenheim mismatch)
        "Independent Researcher, Trondheim, Norway": ("", "", "unmatched", ""),
        
        # Foshan institutions (fix for Foshan Maternity mismatch)
        "ChatEDA Tech, Foshan, China": ("", "", "company", "CN"),
        
        # Fremont institutions (fix for Fremont Bank mismatch)
        "Avalanche Technology,Fremont,CA,United States": ("", "", "company", "US"),
        
        # Nagakute institutions (fix for Numerical Algorithms Group mismatch)
        "Toyota Central R&D Labs., Inc,Nagakute,Japan": ("", "", "company", "JP"),
        
        # Yokkaichi institutions (fix for Yokohama mismatch)
        "Institute of Memory Technology R&D,Kioxia Corporation,Yokkai": ("", "", "company", "JP"),
        
        # Yokohama institutions (fix for Yokohama mismatch)
        "Institute of Memory Technology R&D, Kioxia Corporation,Yokoh": ("", "", "company", "JP"),
        
        # Beijing institutions (fix for Beijing Emergency Medical Center mismatch)
        "Infinigence-AI, Beijing, China": ("", "", "company", "CN"),
        
        # Paris institutions (fix for Université Paris-Saclay mismatch)
        "Nokia Bell Labs,Paris,France": ("", "", "company", "FR"),
        
        # Hsinchu institutions (fix for Museo Egizio mismatch)
        "MediaTek Inc": ("", "", "company", "TW"),
        "MediaTek Inc.,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Mediatek, Hsinchu, Taiwan": ("", "", "company", "TW"),
        
        # Hsinchu institutions (fix for Hospital Santa Izabel mismatch)
        "Macronix International Co., Ltd,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Macronix International Co., Ltd.,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Realtek Semiconductor": ("", "", "company", "TW"),
        "Realtek Semiconductor Corp,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Realtek Semiconductor,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Research Nvidia,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Taiwan SemiconductorManufacturing Company,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Taiwan Semiconductor Research Institute,Hsinchu,Taiwan": ("", "", "company", "TW"),
        
        # Atsugi institutions (fix for Amjet Turbine System mismatch)
        "Sony Semiconductor Solutions Corporation,Atsugi,Japan": ("", "", "company", "JP"),
        
        # Boston institutions (fix for Boston Medical Group mismatch)
        "Lightmatter,Boston,USA": ("", "", "company", "US"),
        
        # Taipei institutions (fix for Taipei Hospital mismatch)
        "Taipei Tech,Taipei,Taiwan,R.O.C.": ("https://openalex.org/I111328349", "National Taipei University of Technology", "education", "TW"),
        
        # Athens institutions (fix for Athens Orthopedic Clinic mismatch)
        "National Technichal University of Athens, Athens, Greece": ("https://openalex.org/I107434878", "National Technical University of Athens", "education", "GR"),
        "Trimsignal, Athens, Attiki, Greece": ("", "", "company", "GR"),
        
        # Torrance institutions (fix for Quincy University mismatch)
        "QuinStar Inc,Torrance,CA,USA": ("", "", "company", "US"),
        
        # Shinjuku institutions (fix for State Hydrological Institute mismatch)
        "Power Diamond Systems Inc.,Shinjuku, Tokyo,Japan": ("", "", "company", "JP"),
        
        # Sayama institutions (fix for Strategic Analysis mismatch)
        "Novel Crystal Technology,Sayama,Japan": ("", "", "company", "JP"),
        
        # Nanjing institutions (fix for Nanjing Institute mismatch)
        "National Center of Technology Innovation for EDA, nanjing, C": ("https://openalex.org/I168600328", "Nanjing University", "education", "CN"),
        "Nanjing Unipower Information Technology Co., Ltd,Nanjing,Chi": ("", "", "company", "CN"),
        
        # Ningbo institutions (fix for Ningbo Transportation mismatch)
        "Ningbo Institute of Digital Twin, Ningbo, China": ("https://openalex.org/I184987418", "Ningbo University", "education", "CN"),
        
        # Malta institutions (fix for GlobalFoundries mismatch)
        "GlobalFoundries, Inc.,Malta,NY,12020": ("", "", "company", "US"),
        
        # Lausanne institutions (fix for EPFL mismatch)
        "EPFL–Ecole Polytechnique Fédérale de Lausanne,Institute of M": ("https://openalex.org/I13326684", "École Polytechnique Fédérale de Lausanne", "education", "CH"),
        
        # Ghent institutions (fix for Ghent University mismatch)
        "Ghent University-Imec,Photonics Research Group,INTEC Departm": ("https://openalex.org/I144955662", "Ghent University", "education", "BE"),
        
        # Reutlingen institutions (fix for Reutlingen University mismatch)
        "Bosch Mobility Electronics,Reutlingen,Germany": ("https://openalex.org/I132823654", "Reutlingen University", "education", "DE"),
        
        # Austin institutions (fix for The University of Texas at Austin mismatch)
        "AMD, Austin, TX, USA": ("", "", "company", "US"),
        "Cadence Design System, Inc.,Austin,TX": ("", "", "company", "US"),
        "Intel,Austin,TX,USA": ("", "", "company", "US"),
        "NVIDIA Research, Austin, USA": ("", "", "company", "US"),
        "Research Nvidia,Austin,Texas,USA": ("", "", "company", "US"),
        
        # TCAD (fix for Temple College mismatch)
        "TCAD": ("", "", "unmatched", ""),
        
        # DEIB (fix for Dayalbagh Educational Institute mismatch)
        "Politecnico di Milano and IUNET,Informazione e Bioingegneria": ("https://openalex.org/I105358227", "Politecnico di Milano", "education", "IT"),
        
        # CSIT (fix for Clayton Sleep Institute mismatch)
        "Queen's University Belfast,Centre for Secure Information Tec": ("https://openalex.org/I144011827", "Queen's University Belfast", "education", "GB"),
        
        # Huawei (fix for Haramaya University mismatch)
        "Noah's Ark Lab, Huawei": ("", "", "company", ""),
        "Noah's Ark Lab, Huawei, Shatin, Hong Kong": ("", "", "company", "HK"),
        "Noah's Ark Lab, Huawei, Shenzhen, China": ("", "", "company", "CN"),
        
        # Mediatek (fix for Museo Egizio mismatch)
        "MediaTek Inc": ("", "", "company", "TW"),
        "MediaTek Inc.,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Mediatek, Hsinchu, Taiwan": ("", "", "company", "TW"),
        
        # Nvidia (fix for Norwegian Veterinary Institute mismatch)
        "NVIDIA": ("", "", "company", ""),
        "NVIDIA Corp.": ("", "", "company", ""),
        "NVIDIA Corporation": ("", "", "company", ""),
        "NVIDIA, Austin, Texas, USA": ("", "", "company", "US"),
        "NVIDIA, Austin, USA": ("", "", "company", "US"),
        "NVIDIA,Austin,TX,US": ("", "", "company", "US"),
        "Nvidia": ("", "", "company", ""),
        "Nvidia Corporation": ("", "", "company", ""),
        "Nvidia Corporation, Austin, Texas, USA": ("", "", "company", "US"),
        "Nvidia,USA": ("", "", "company", "US"),
        
        # Intel (fix for Intel (Malaysia) mismatch)
        "Intel": ("", "", "company", ""),
        "Intel Corporation": ("", "", "company", ""),
        "Intel Corporation,Components Research,Hillsboro,OR,USA": ("", "", "company", "US"),
        "Intel Corporation,Components Research,Hillsboro,OR,USA,97124": ("", "", "company", "US"),
        "Intel Corporation,Components Research,Hillsboro,OR,USA,97214": ("", "", "company", "US"),
        "Intel Corporation,Corporate Quality Network,Hillsboro,OR,USA": ("", "", "company", "US"),
        "Intel Corporation,Design Enablement,Hillsboro,OR,USA,97124": ("", "", "company", "US"),
        "Intel Corporation,Global Sourcing for Equipment and Material": ("", "", "company", ""),
        "Intel Corporation,Intel Labs,Hillsboro,Oregon": ("", "", "company", "US"),
        "Intel Corporation,Portland Technology Development,Hillsboro,": ("", "", "company", "US"),
        "Intel,Austin,TX,USA": ("", "", "company", "US"),
        "Intel,Chandler,AZ,USA": ("", "", "company", "US"),
        "Intel,Hillsboro,OR,USA": ("", "", "company", "US"),
        "Intel,Portland,OR,USA": ("", "", "company", "US"),
        
        # Synopsys (fix for Synopsys (Germany) mismatch)
        "Synopsys": ("", "", "company", ""),
        "Synopsys Inc": ("", "", "company", ""),
        "Synopsys Inc.": ("", "", "company", ""),
        "Synopsys Inc.,": ("", "", "company", ""),
        "Synopsys, Inc": ("", "", "company", ""),
        "Synopsys, Inc.": ("", "", "company", ""),
        "Synopsys, Inc.,": ("", "", "company", ""),
        "Synopsys, Inc.,Sunnyvale,CA,USA": ("", "", "company", "US"),
        "Synopsys, Inc., Sunnyvale, USA": ("", "", "company", "US"),
        "Synopsys, Inc.,Taipei,Taiwan": ("", "", "company", "TW"),
        "Synopsys, Inc,Hsinchu,Taiwan": ("", "", "company", "TW"),
        "Synopsys,Inc": ("", "", "company", ""),
        "Synopsys,Inc.,Aachen,Germany": ("", "", "company", "DE"),
        "Synopsys Inc.,Leuven,Belgium": ("", "", "company", "BE"),
        "Synopsys Inc.,Ottawa,Canada": ("", "", "company", "CA"),
        "Synopsys Inc.,Sunnyvale,CA,USA": ("", "", "company", "US"),
        "Synopsys Inc.,Sunnyvale,USA": ("", "", "company", "US"),
        "Synopsys,California,US": ("", "", "company", "US"),
        
        # Siemens (fix for Siemens (Hungary) mismatch)
        "Siemens": ("", "", "company", ""),
        
        # SoMaS (fix for Science Oxford mismatch)
        "SoMaS, The University of Sheffield, Sheffield, United Kingdo": ("https://openalex.org/I126089217", "University of Sheffield", "education", "GB"),
        
        # Soitec (fix for Science Oxford mismatch)
        "Soitec": ("", "", "company", ""),
        "Soitec,Bernin,France": ("", "", "company", "FR"),
        
        # State Key Lab (fix for State Key Lab of Oil and Gas mismatch)
        "State Key Laboratory of Integrated Chips and Systems (SKLICS": ("https://openalex.org/I137521230", "Fudan University", "education", "CN"),
        
        # S2C Inc (fix for Shenzhen Planck Innovation mismatch)
        "S2C Inc., Shenzhen, China": ("", "", "company", "CN"),
        
        # Shenzhen Institute (fix for Shenzhen Planck Innovation mismatch)
        "Shenzhen Institute of Artificial Intelligence and Robotics f": ("https://openalex.org/I137763257", "Chinese University of Hong Kong", "education", "HK"),
        
        # Tencent (fix for Shenzhen Planck Innovation mismatch)
        "Tencent Quantum Lab, Shenzhen, Guangdong, China": ("", "", "company", "CN"),
        
        # ZTE (fix for Shenzhen Planck Innovation mismatch)
        "ZTE,State Key Lab of Mobile Network and Mobile Communication": ("", "", "company", "CN"),
        
        # Wuhan (fix for Wuhan Science and Technology Bureau mismatch)
        "Wuhan JinYinHu Laboratory, Wuhan, Hubei, China": ("https://openalex.org/I150368142", "Wuhan University", "education", "CN"),
        
        # Zhicun Research Lab (fix for Beijing Geriatric Hospital mismatch)
        "Zhicun Research Lab,Beijing,China": ("", "", "company", "CN"),
        
        # UniVista (fix for Shanghai Institute mismatch)
        "UniVista Industrial Software Group,Shanghai,China": ("", "", "company", "CN"),
        
        # Pathfinding (fix for Consumer Healthcare Products Association mismatch)
        "Pathfinding Co-Optimization Technology & Systems (PACTS) Ime": ("", "", "company", ""),
        
        # SiMa (fix for Saveetha University mismatch)
        "SiMa,USA": ("", "", "company", "US"),
        
        # Nokia Bell Labs (fix for Université Paris-Saclay mismatch)
        "Nokia Bell Labs,Paris,France": ("", "", "company", "FR"),
        
        # Huawei Technologies R&D (fix for KU Leuven mismatch)
        "Huawei Technologies R&D,Leuven,Belgium": ("", "", "company", "BE"),
        
        # Infinigence-AI (fix for SAIC-GM mismatch)
        "Infinigence-AI, Shanghai, China": ("", "", "company", "CN"),
    }
    
    # Apply corrections
    corrected = 0
    for raw_affiliation, (inst_id, inst_name, inst_type, country) in corrections.items():
        if raw_affiliation in mapping and mapping[raw_affiliation]["status"] == "review":
            mapping[raw_affiliation]["institution_id"] = inst_id
            mapping[raw_affiliation]["institution_name"] = inst_name
            mapping[raw_affiliation]["institution_type"] = inst_type
            mapping[raw_affiliation]["country_code"] = country
            mapping[raw_affiliation]["lineage"] = ""
            mapping[raw_affiliation]["status"] = "manual"
            corrected += 1
            print(f"  Corrected: {raw_affiliation[:50]:50} -> {inst_name[:40] or 'UNMATCHED'}")
    
    print(f"\nCorrected {corrected} review cases")
    
    # Save
    save_map(mapping)
    print(f"Saved to {MAP_CSV}")
    
    # Coverage report
    all_strings = {}
    for v in sorted(d for d in os.listdir(os.path.join(REPO_ROOT, "cache")) if os.path.isdir(os.path.join(REPO_ROOT, "cache", d))):
        venue_dir = os.path.join(REPO_ROOT, "cache", v)
        for y in os.listdir(venue_dir):
            if y.isdigit():
                works_file = os.path.join(venue_dir, y, "works.jsonl")
                if os.path.exists(works_file):
                    with open(works_file) as f:
                        for line in f:
                            w = json.loads(line)
                            for a in w.get("authorships", []):
                                for s in a.get("raw_affiliations", []) or []:
                                    all_strings[s] = all_strings.get(s, 0) + 1
    
    by_status = {}
    weighted = {}
    for s, count in all_strings.items():
        row = mapping.get(s)
        st = row["status"] if row else "unmapped"
        by_status[st] = by_status.get(st, 0) + 1
        weighted[st] = weighted.get(st, 0) + count
    
    total_occ = sum(all_strings.values())
    print(f"\n{'status':<12}{'distinct':>10}{'occurrences':>14}{'% of occurrences':>18}")
    for st in ("auto", "manual", "review", "unmatched", "unmapped"):
        if st in by_status:
            print(f"{st:<12}{by_status[st]:>10}{weighted[st]:>14}{100*weighted[st]/max(total_occ,1):>17.1f}%")


if __name__ == "__main__":
    main()
